"""add tenant scoping to trusts

Revision ID: 57cdbc23dd16
Revises: dbd5fe7ee652
Create Date: 2026-09-15 20:58:39.393314

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '57cdbc23dd16'
down_revision: Union[str, Sequence[str], None] = 'dbd5fe7ee652'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # SECURITY REVIEW (tenant isolation): Trust records are owned by a tenant;
    # the processing key is scoped by tenant in the application layer. This
    # column is nullable for legacy / local runs without API-key identity.
    with op.batch_alter_table('trusts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tenant_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_trusts_tenant_id'), ['tenant_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_trusts_tenant_id_tenants', 'tenants', ['tenant_id'], ['id']
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('trusts', schema=None) as batch_op:
        batch_op.drop_constraint('fk_trusts_tenant_id_tenants', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_trusts_tenant_id'))
        batch_op.drop_column('tenant_id')
