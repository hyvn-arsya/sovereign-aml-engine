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

        if container_image is None:
            container_image = ecs.ContainerImage.from_asset(
                str(PROJECT_ROOT),
                file="Dockerfile",
            )

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

        # SECURITY REVIEW (Critical): the pipeline requires LLM provider keys
        # (LlamaParse, Gemini, Anthropic) which the CDK stack was not injecting.
        # A single JSON secret holds all three; the operator populates the actual
        # values in Secrets Manager before deploying the ECS task.
        llm_secret = sm.Secret(
            self, "LlmCredentials",
            description="LLM API keys for the sovereign AML pipeline",
            generate_secret_string=sm.SecretStringGenerator(
                generate_string_key="placeholder",
                secret_string_template='{"LLAMACLOUD_API_KEY":"replace","GOOGLE_API_KEY":"replace","ANTHROPIC_API_KEY":"replace"}',
            ),
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
                environment={
                    "ENV": env,
                    "S3_BUCKET": raw_bucket.bucket_name,
                    "AUDIT_BUCKET": audit_bucket.bucket_name,
                },
                secrets={
                    "DB_HOST": ecs.Secret.from_secrets_manager(db_secret, "host"),
                    "DB_USER": ecs.Secret.from_secrets_manager(db_secret, "username"),
                    "DB_PASS": ecs.Secret.from_secrets_manager(db_secret, "password"),
                    "DB_NAME": ecs.Secret.from_secrets_manager(db_secret, "dbname"),
                    "LLAMACLOUD_API_KEY": ecs.Secret.from_secrets_manager(llm_secret, "LLAMACLOUD_API_KEY"),
                    "GOOGLE_API_KEY": ecs.Secret.from_secrets_manager(llm_secret, "GOOGLE_API_KEY"),
                    "ANTHROPIC_API_KEY": ecs.Secret.from_secrets_manager(llm_secret, "ANTHROPIC_API_KEY"),
                },
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

        # SECURITY REVIEW (Critical): the Fargate tasks had no network path to
        # PostgreSQL.  The RDS instance lives in PRIVATE_WITH_EGRESS subnets;
        # allow the ECS service security group to reach it on port 5432.
        database.connections.allow_default_port_from(
            fargate_service.service,
            description="Fargate service → PostgreSQL",
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

        # --- Tags ---

        Tags.of(self).add("Project", "sovereign-aml")
        Tags.of(self).add("Environment", env)
        Tags.of(self).add("ManagedBy", "cdk")
