from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import os
import sys

# Add your app directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import your database URL and Base
from app.database import DATABASE_URL
from app.db.base import Base

# Import all models so they're registered with Base
from app.models.user import User, UserPreference
from app.models.tenant import Tenant
from app.models.payment import Payment, Subscription, Invoice, PaymentGatewayLog
from app.models.property import Property, Unit
from app.models.maintenance import MaintenanceRequest
from app.models.staff import Staff
from app.models.attendance import Attendance, LeaveRequest, AttendanceSummary
from app.models.meter import MeterReading

# this is the Alembic Config object
config = context.config

# Set the SQLAlchemy URL from your database.py
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate support
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()