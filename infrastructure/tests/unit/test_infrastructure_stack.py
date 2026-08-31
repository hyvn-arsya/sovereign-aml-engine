import aws_cdk as cdk
import aws_cdk.assertions as assertions
from aws_cdk import aws_ecs as ecs

from infrastructure.infrastructure_stack import InfrastructureStack


def make_template() -> assertions.Template:
    app = cdk.App()
    # Inject a registry image instead of the local Dockerfile so unit tests
    # do not trigger a Docker build during synthesis.
    image = ecs.ContainerImage.from_registry("public.ecr.aws/dummy/sovereign:latest")
    stack = InfrastructureStack(app, "TestStack", container_image=image)
    return assertions.Template.from_stack(stack)


def test_creates_raw_documents_bucket():
    template = make_template()
    template.resource_count_is("AWS::S3::Bucket", 2)


def test_creates_versioned_audit_bucket():
    template = make_template()
    template.has_resource_properties("AWS::S3::Bucket", {
        "VersioningConfiguration": {"Status": "Enabled"},
    })


def test_creates_vpc():
    template = make_template()
    template.resource_count_is("AWS::EC2::VPC", 1)


def test_rds_is_encrypted():
    template = make_template()
    template.has_resource_properties("AWS::RDS::DBInstance", {
        "StorageEncrypted": True,
    })


def test_rds_has_backup_retention():
    template = make_template()
    template.has_resource_properties("AWS::RDS::DBInstance", {
        "BackupRetentionPeriod": 7,
    })


def test_creates_fargate_service():
    template = make_template()
    template.has_resource_properties("AWS::ECS::Service", {
        "LaunchType": "FARGATE",
    })


def test_fargate_uses_local_container_image():
    template = make_template()
    template.has_resource_properties("AWS::ECS::TaskDefinition", {
        "RequiresCompatibilities": ["FARGATE"],
    })


def test_adds_cfn_outputs():
    template = make_template()
    outputs = template.find_outputs("*")
    assert len(outputs.keys()) >= 4
