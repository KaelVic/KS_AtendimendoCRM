"""Create the empty foundation baseline.

Revision ID: 0001_foundation_baseline
Revises:
"""
from typing import Sequence, Union

revision: str = "0001_foundation_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
