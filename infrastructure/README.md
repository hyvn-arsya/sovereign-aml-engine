# Infrastructure — AWS CDK (Python)

Production deployment for the **Sovereign AML Engine** using the [AWS CDK](https://aws.amazon.com/cdk/) (Python).

## What it provisions

- **S3** — raw-document bucket + append-only audit bucket (versioned)
- **VPC** with CloudWatch flow logs on all traffic
- **RDS PostgreSQL** — encrypted at rest, 7-day automated backup retention
- **ECS Fargate** (FastAPI app) behind an **Application Load Balancer** with `/health` checks
- Optional **HTTPS** via ACM certificate + HTTP→HTTPS redirect (set `certificate_arn`)
- Deployment **circuit breaker**, `min_healthy_percent`, cost-allocation tags, `CfnOutputs`
- `env` (dev/prod) parameterization via CDK context

Read the app source in [`infrastructure/infrastructure_stack.py`](infrastructure/infrastructure_stack.py).

## Deploy

```bash
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt -r requirements-dev.txt
cdk synth                          # "-c env=prod" for the prod profile
cdk deploy SovereignAml-dev        # or SovereignAml-prod
```

## Tests

```bash
pytest infrastructure/tests/unit
```

The unit tests synthesise the stack and assert on the resulting CloudFormation
template (S3 bucket count, RDS encryption/backups, Fargate launch type, outputs).
