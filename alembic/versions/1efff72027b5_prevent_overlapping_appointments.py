"""prevent overlapping appointments

Revision ID: 1efff72027b5
Revises: cb54045ea9b1
Create Date: 2026-11-15 14:18:44.971775

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1efff72027b5'
down_revision: Union[str, Sequence[str], None] = 'cb54045ea9b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # btree_gist нужен, чтобы в одном GiST-индексе сравнивать и число (=), и диапазон (&&).
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        """
        ALTER TABLE appointments
        ADD CONSTRAINT ex_appointments_no_overlap
        EXCLUDE USING gist (
            barber_id WITH =,
            tstzrange(start_at, end_at, '[)') WITH &&
        )
        WHERE (status = 'booked')
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE appointments DROP CONSTRAINT ex_appointments_no_overlap")
