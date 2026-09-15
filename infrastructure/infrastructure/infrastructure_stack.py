import os
from pathlib import Path

from aws_cdk import (
    Stack,
    RemovalPolicy,
    CfnOutput,
    Tags,
    Duration,
    aws_s3 as s3,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_certificatemanager as acm,
    aws_logs as logs,
    aws_secretsmanager as sm,
)
from constructs import Construct

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class InfrastructureStack(Stack):

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        container_image: ecs.ContainerImage | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env = self.node.try_get_context("env") or "dev"
        is_prod = env == "prod"

        if container_image is None:
            container_image = ecs.ContainerImage.from_asset(
                str(PROJECT_ROOT),
                file="Dockerfile",
            )

        # ── SECURITY REVIEW (P0): operator-provisioned secrets ──────────────
        # The stack NEVER ships throwaway or "replace"-valued credentials into
        # a deployable task. The exact Secrets Manager ARNs are supplied by the
        # operator per environment (CDK context `-c llm_credentials_arn=...`
        # `-c app_secrets_arn=...`, or LLM_CREDENTIALS_ARN / APP_SECRETS_ARN env):
        #   * llm_credentials_secret : {LLAMACLOUD_API_KEY, GOOGLE_API_KEY,
        #                                ANTHROPIC_API_KEY}
        #   * app_secret               : {API_KEY_SALT, SEED_API_KEYS,
        #                                DFAT_SOURCE_URL, PEP_API_KEY}
        # Production synthesis FAILS unless both ARNs are present, so a "demo
        # screening, no API keys" production service cannot be deployed by
        # accident. Dev keeps a generated LLM secret so `cdk synth` stays a
        # no-dependency exercise.
        llm_credentials_arn = (
            self.node.try_get_context("llm_credentials_arn")
            or os.environ.get("LLM_CREDENTIALS_ARN")
        )
        app_secrets_arn = (
            self.node.try_get_context("app_secrets_arn")
            or os.environ.get("APP_SECRETS_ARN")
        )
        if is_prod and (not llm_credentials_arn or not app_secrets_arn):
            raise ValueError(
                "Production synthesis requires operator-provided Secrets Manager "
                "ARNs: -c llm_credentials_arn=... and -c app_secrets_arn=... "
                "(or LLM_CREDENTIALS_ARN / APP_SECRETS_ARN env vars). Refusing to "
                "generate placeholder credentials for a production deploy."
            )

        if llm_credentials_arn:
            llm_secret = sm.Secret.from_secret_complete_arn(
                self, "LlmCredentials", llm_credentials_arn
            )
            llm_secret_is_generated = False
        else:
            # Dev-only convenience: a real (random) generated secret, clearly
            # documented. Production path above prevents this from ever being
            # deployable outside dev.
            llm_secret = sm.Secret(
                self, "LlmCredentials",
                description="LLM API keys for the sovereign AML pipeline (dev default)",
                generate_secret_string=sm.SecretStringGenerator(
                    exclude_punctuation=True,
                ),
            )
            llm_secret_is_generated = True

        if app_secrets_arn:
            app_secret = sm.Secret.from_secret_complete_arn(
                self, "AppConfig", app_secrets_arn
            )
        else:
            app_secret = None

        # --- S3 Buckets ---

        raw_bucket = s3.Bucket(
            self, "RawDocumentsBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
        )

        audit_bucket = s3.Bucket(
            self, "AuditLogsBucket",
            removal_policy=RemovalPolicy.RETAIN,
            versioned=True,
            # SECURITY REVIEW (High): 7-year retention was documented but not
            # enforced in IaC.  Object Lock + Compliance-mode default retention
            # makes WORM durable and non-overridable (even by an operator).
            object_lock_enabled=True,
            object_lock_default_retention=s3.ObjectLockRetention.compliance(
                Duration.days(2555),  # ~7 years
            ),
            # Bucket-level default encryption so every new object is encrypted
            # at rest even when the put_object call omits ServerSideEncryption.
            encryption=s3.BucketEncryption.S3_MANAGED,
        )

        # --- VPC ---

        vpc = ec2.Vpc(
            self, "SovereignVpc",
            max_azs=2,
            nat_gateways=1,
        )

        vpc.add_flow_log(
            "FlowLog",
            destination=ec2.FlowLogDestination.to_cloud_watch_logs(
                log_group=logs.LogGroup(
                    self, "VpcFlowLogGroup",
                    retention=logs.RetentionDays.ONE_WEEK,
                ),
            ),
            traffic_type=ec2.FlowLogTrafficType.ALL,
        )

        # --- ECS Cluster ---

        cluster = ecs.Cluster(
            self, "SovereignCluster",
            vpc=vpc,
        )

        # --- RDS PostgreSQL ---

        db_secret = rds.DatabaseSecret(
            self, "DatabaseSecret",
            username="postgres",
        )

        database = rds.DatabaseInstance(
            self, "SovereignDatabase",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_16,
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO,
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            ),
            credentials=rds.Credentials.from_secret(db_secret),
            database_name="sovereign",
            storage_encrypted=True,
            backup_retention=Duration.days(7),
            deletion_protection=env == "prod",
            removal_policy=(
                RemovalPolicy.RETAIN if env == "prod"
                else RemovalPolicy.DESTROY
            ),
        )

        # --- HTTPS Certificate (optional) ---

        certificate_arn = self.node.try_get_context("certificate_arn")
        certificate = None

        if certificate_arn:
            certificate = acm.Certificate.from_certificate_arn(
                self, "Certificate",
                certificate_arn=certificate_arn,
            )

        # --- ECS Fargate ---

        # SECURITY REVIEW (P0): all required production settings are injected.
        # API_KEY_SALT / SEED_API_KEYS / DFAT_SOURCE_URL / PEP_API_KEY come from
        # the operator's app secret; without it (dev) they are simply absent and
        # the runtime uses demo mode + the development salt.
        task_secrets = {
            "DB_HOST": ecs.Secret.from_secrets_manager(db_secret, "host"),
            "DB_USER": ecs.Secret.from_secrets_manager(db_secret, "username"),
            "DB_PASS": ecs.Secret.from_secrets_manager(db_secret, "password"),
            "DB_NAME": ecs.Secret.from_secrets_manager(db_secret, "dbname"),
            "LLAMACLOUD_API_KEY": ecs.Secret.from_secrets_manager(llm_secret, "LLAMACLOUD_API_KEY"),
            "GOOGLE_API_KEY": ecs.Secret.from_secrets_manager(llm_secret, "GOOGLE_API_KEY"),
            "ANTHROPIC_API_KEY": ecs.Secret.from_secrets_manager(llm_secret, "ANTHROPIC_API_KEY"),
        }
        if app_secret is not None:
            task_secrets.update({
                "API_KEY_SALT": ecs.Secret.from_secrets_manager(app_secret, "API_KEY_SALT"),
                "SEED_API_KEYS": ecs.Secret.from_secrets_manager(app_secret, "SEED_API_KEYS"),
                "DFAT_SOURCE_URL": ecs.Secret.from_secrets_manager(app_secret, "DFAT_SOURCE_URL"),
                "PEP_API_KEY": ecs.Secret.from_secrets_manager(app_secret, "PEP_API_KEY"),
            })

        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "SovereignFargateService",
            cluster=cluster,
            cpu=512,
            memory_limit_mib=1024,
            desired_count=1,
            circuit_breaker=ecs.DeploymentCircuitBreaker(
                rollback=True,
            ),
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=container_image,
                container_port=8000,
                # SECURITY REVIEW (P0): the task previously defaulted to DEMO
                # screening with no API keys in prod. The screening mode is now
                # pinned explicitly, and every production setting comes from the
                # operator's Secrets Manager secret rather than baked-in values.
                environment={
                    "ENV": env,
                    "S3_BUCKET": raw_bucket.bucket_name,
                    "AUDIT_BUCKET": audit_bucket.bucket_name,
                    "SCREENING_MODE": "production" if is_prod else "demo",
                },
                secrets=task_secrets,
                log_driver=ecs.LogDrivers.aws_logs(
                    stream_prefix="fargate",
                    log_group=logs.LogGroup(
                        self, "FargateLogGroup",
                        retention=logs.RetentionDays.ONE_WEEK,
                    ),
                ),
            ),
            public_load_balancer=True,
            certificate=certificate,
            redirect_http=certificate is not None,
            health_check=ecs.HealthCheck(
                command=["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(60),
            ),
            health_check_grace_period=Duration.seconds(120),
            min_healthy_percent=100,
        )

        raw_bucket.grant_read_write(fargate_service.task_definition.task_role)
        audit_bucket.grant_write(fargate_service.task_definition.task_role)

        # Importer secrets (from_secret_complete_arn) do not auto-grant the
        # execution role; the service needs GetSecretValue for the DB and LLM
        # credentials plus the app config.
        service_execution_role = fargate_service.task_definition.execution_role
        db_secret.grant_read(service_execution_role)
        llm_secret.grant_read(service_execution_role)
        if app_secret is not None:
            app_secret.grant_read(service_execution_role)

        # SECURITY REVIEW (Critical): the Fargate tasks had no network path to
        # PostgreSQL.  The RDS instance lives in PRIVATE_WITH_EGRESS subnets;
        # allow the ECS service security group to reach it on port 5432.
        database.connections.allow_default_port_from(
            fargate_service.service,
            description="Fargate service → PostgreSQL",
        )

        # ── SECURITY REVIEW (P1): DB migrations as a separate one-off task ────
        # A fresh RDS instance previously shipped with NO tables because the
        # container runs `uvicorn api:app` directly. Migrations are NOT run at
        # application startup (that would make a crashed/interrupted migration
        # take the serving task down with it); instead a dedicated Fargate task
        # runs `alembic upgrade head` against the same image, same DB secrets,
        # same network path. Deploy step: `aws ecs run-task` (see README).
        migration_log_group = logs.LogGroup(
            self, "MigrationLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
        )
        # The raw FargateTaskDefinition is not IConnectable; give the one-off
        # run-task its own security group and open the DB to it.
        migration_sg = ec2.SecurityGroup(
            self, "MigrationTaskSecurityGroup",
            vpc=vpc,
            description="One-off alembic migration run-task",
            allow_all_outbound=True,
        )
        database.connections.allow_from(
            migration_sg,
            ec2.Port.tcp(5432),
            description="Migration run-task → PostgreSQL",
        )
        migration_task = ecs.FargateTaskDefinition(
            self, "MigrationTaskDefinition",
            cpu=256,
            memory_limit_mib=512,
        )
        migration_task.add_container(
            "MigrateContainer",
            image=container_image,
            command=["alembic", "upgrade", "head"],
            environment={"ENV": env},
            secrets={
                "DB_HOST": ecs.Secret.from_secrets_manager(db_secret, "host"),
                "DB_USER": ecs.Secret.from_secrets_manager(db_secret, "username"),
                "DB_PASS": ecs.Secret.from_secrets_manager(db_secret, "password"),
                "DB_NAME": ecs.Secret.from_secrets_manager(db_secret, "dbname"),
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="migrate",
                log_group=migration_log_group,
            ),
        )
        db_secret.grant_read(migration_task.execution_role)
        CfnOutput(
            self, "MigrationTaskSecurityGroupId",
            value=migration_sg.security_group_id,
            description="Security group to attach when running the migration run-task",
        )

        # --- Outputs ---

        CfnOutput(
            self, "LoadBalancerDns",
            value=fargate_service.load_balancer.load_balancer_dns_name,
            description="ALB DNS name",
        )

        CfnOutput(
            self, "DatabaseEndpoint",
            value=database.db_instance_endpoint_address,
            description="RDS PostgreSQL endpoint",
        )

        CfnOutput(
            self, "RawBucketName",
            value=raw_bucket.bucket_name,
            description="S3 bucket for raw trust deed documents",
        )

        CfnOutput(
            self, "AuditBucketName",
            value=audit_bucket.bucket_name,
            description="S3 bucket for audit logs",
        )

        CfnOutput(
            self, "MigrationTaskDefinitionFamily",
            value=migration_task.family,
            description=(
                "One-off migration task; run with `aws ecs run-task --task-definition "
                f"{migration_task.family} --launch-type FARGATE --network-configuration ...` "
                "(see README Deploying step 3)"
            ),
        )

        # --- Tags ---

        Tags.of(self).add("Project", "sovereign-aml")
        Tags.of(self).add("Environment", env)
        Tags.of(self).add("ManagedBy", "cdk")
