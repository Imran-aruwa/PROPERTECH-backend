"""Add email verification token columns to users

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-03-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'l2m3n4o5p6q7'
down_revision = 'k1l2m3n4o5p6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS email_verification_token VARCHAR(255),
        ADD COLUMN IF NOT EXISTS email_verification_token_expires_at TIMESTAMP WITH TIME ZONE;
    """)
    # Auto-verify all pre-existing users so they are not locked out.
    # New registrations will go through the full email verification flow.
    op.execute("""
        UPDATE users SET email_verified = TRUE
        WHERE email_verified = FALSE
          AND email_verification_token IS NULL;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email_verification_token;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email_verification_token_expires_at;")
