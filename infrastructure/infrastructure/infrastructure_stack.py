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
)
from constructs import Construct


class InfrastructureStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env = self.node.try_get_context("env") or "dev"

        # --- S3 Buckets ---

        raw_bucket = s3.Bucket(
            self, "RawDocumentsBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        audit_bucket = s3.Bucket(
            self, "AuditLogsBucket",
            removal_policy=RemovalPolicy.RETAIN,
            versioned=True,
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
                image=ecs.ContainerImage.from_asset(
                    "..",
                    file="Dockerfile",
                ),
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
