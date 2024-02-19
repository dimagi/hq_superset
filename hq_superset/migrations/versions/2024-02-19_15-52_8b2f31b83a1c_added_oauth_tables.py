"""Added OAuth tables

Revision ID: 8b2f31b83a1c
Revises: 
Create Date: 2024-02-19 15:52:18.896738

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b2f31b83a1c'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('hq_oauth_client',
        sa.Column('client_id', sa.String(length=48), nullable=True),
        sa.Column('client_secret', sa.String(length=255), nullable=True),
        sa.Column('client_id_issued_at', sa.Integer(), nullable=False),
        sa.Column('client_secret_expires_at', sa.Integer(), nullable=False),
        sa.Column('client_metadata', sa.Text(), nullable=True),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('domain'),
        info={'bind_key': 'HQ Data'},
    )
    op.create_index(
        op.f('ix_hq_oauth_client_client_id'),
        'hq_oauth_client', ['client_id'],
        unique=False,
    )
    op.create_table('hq_oauth_token',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('client_id', sa.String(length=40), nullable=False),
        sa.Column('token_type', sa.String(length=40), nullable=True),
        sa.Column('access_token', sa.String(length=255), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=True),
        sa.Column('issued_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('scope', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('access_token'),
        info={'bind_key': 'HQ Data'},
    )
    op.create_index(
        op.f('ix_hq_oauth_token_client_id'),
        'hq_oauth_token',
        ['client_id'],
        unique=False,
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(
        op.f('ix_hq_oauth_token_client_id'),
        table_name='hq_oauth_token',
    )
    op.drop_table('hq_oauth_token')
    op.drop_index(
        op.f('ix_hq_oauth_client_client_id'),
        table_name='hq_oauth_client',
    )
    op.drop_table('hq_oauth_client')
    # ### end Alembic commands ###
