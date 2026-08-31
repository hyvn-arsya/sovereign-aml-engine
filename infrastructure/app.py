#!/usr/bin/env python3

import os

import aws_cdk as cdk

from infrastructure.infrastructure_stack import InfrastructureStack

app = cdk.App()

env = app.node.try_get_context("env") or "dev"

stack = InfrastructureStack(
    app, f"SovereignAml-{env}",
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION"),
    ),
)

app.synth()
