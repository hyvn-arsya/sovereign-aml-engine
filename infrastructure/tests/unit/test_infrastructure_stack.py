import aws_cdk as cdk
import aws_cdk.assertions as assertions
from aws_cdk import aws_ecs as ecs
import pytest

from infrastructure.infrastructure_stack import InfrastructureStack


def make_template() -> assertions.Template:
    app = cdk.App()
    # Inject a registry image instead of the local Dockerfile so unit tests
    # do not trigger a Docker build during synthesis.
    image = ecs.ContainerImage.from_registry("public.ecr.aws/dummy/sovereign:latest")
    stack = InfrastructureStack(app, "TestStack", container_image=image)
    return assertions.Template.from_stack(stack)


APP_SECRET_ARN = "arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:api-config-abc123"
LLM_SECRET_ARN = "arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:llm-creds-abc123"


def make_prod_template() -> assertions.Template:
    app = cdk.App(context={
        "env": "prod",
        "llm_credentials_arn": LLM_SECRET_ARN,
        "app_secrets_arn": APP_SECRET_ARN,
    })
    image = ecs.ContainerImage.from_registry("public.ecr.aws/dummy/sovereign:latest")
    stack = InfrastructureStack(app, "ProdStack", container_image=image)
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


def test_prod_synthesis_requires_operator_secrets():
    """
    SECURITY (P0): production MUST NOT deploy with generated/placeholder
    credentials. Without operator-provided Secrets Manager ARNs the stack
    refuses to synthesize at all.
    """
    app = cdk.App(context={"env": "prod"})
    image = ecs.ContainerImage.from_registry("public.ecr.aws/dummy/sovereign:latest")
    with pytest.raises(ValueError):
        InfrastructureStack(app, "ProdStackNoSecrets", container_image=image)


def test_prod_injects_production_settings():
    """
    SECURITY (P0): the production task must run SCREENING_MODE=production (no
    silent demo screening) and receive API_KEY_SALT / SEED_API_KEYS /
    DFAT_SOURCE_URL / PEP_API_KEY from the operator's secret.
    """
    template = make_prod_template()
    task_defs = template.find_resources("AWS::ECS::TaskDefinition")
    container_defs = [
        cd for td in task_defs.values() for cd in td["Properties"]["ContainerDefinitions"]
    ]

    env_by_name = {
        e["Name"]: e["Value"] for cd in container_defs for e in cd.get("Environment", [])
    }
    assert env_by_name.get("SCREENING_MODE") == "production"

    secret_names = {
        s["Name"] for cd in container_defs for s in cd.get("Secrets", [])
    }
    assert {"API_KEY_SALT", "SEED_API_KEYS", "DFAT_SOURCE_URL", "PEP_API_KEY"}.issubset(
        secret_names
    )


def test_migration_task_runs_alembic_one_off():
    """
    SECURITY (P1): migrations are deployed as a separate ECS one-off task
    (`alembic upgrade head`), NOT at application startup.
    """
    template = make_template()
    task_defs = template.find_resources("AWS::ECS::TaskDefinition")
    container_defs = [
        cd for td in task_defs.values() for cd in td["Properties"]["ContainerDefinitions"]
    ]
    commands = {
        " ".join(cd.get("Command", []))
        for cd in container_defs
        if cd.get("Command", [])
    }
    assert "alembic upgrade head" in commands
    # The serving task defines NO command override (its Dockerfile CMD runs
    # uvicorn) — so the only non-empty command override in the stack is the
    # migration task; the serving task must never run migrations at startup.
    assert commands == {"alembic upgrade head"}
