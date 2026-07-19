"""storage baseline"""
from alembic import op
import sqlalchemy as sa
revision="0001_storage_baseline"; down_revision=None; branch_labels=None; depends_on=None
def upgrade():
    # The application initializer owns the portable SQLAlchemy schema creation.
    pass
def downgrade(): pass
