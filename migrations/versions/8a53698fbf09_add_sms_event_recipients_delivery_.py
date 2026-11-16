"""Add SMS event recipients delivery reports and submission tracking"""

import sqlalchemy as sa
from alembic import op

revision = "8a53698fbf09"
down_revision = "ccdd15d2f274"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sms_delivery_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("phone", sa.String(length=13), nullable=True),
        sa.Column("failure_reason", sa.String(length=80), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_message_id", "status"),
    )
    op.create_index(
        op.f("ix_sms_delivery_reports_provider_message_id"),
        "sms_delivery_reports",
        ["provider_message_id"],
        unique=False,
    )
    op.add_column(
        "notifications", sa.Column("recipient_user_id", sa.Integer(), nullable=True)
    )
    op.add_column("notifications", sa.Column("order_id", sa.Integer(), nullable=True))
    op.add_column(
        "notifications", sa.Column("event_type", sa.String(length=30), nullable=True)
    )
    op.add_column(
        "notifications",
        sa.Column("provider_message_id", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "notifications", sa.Column("last_error", sa.String(length=80), nullable=True)
    )
    op.add_column(
        "notifications",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "notifications",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_notifications_order_id"), "notifications", ["order_id"], unique=False
    )
    op.create_index(
        op.f("ix_notifications_recipient_user_id"),
        "notifications",
        ["recipient_user_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "notifications_provider_message_id_key",
        "notifications",
        ["provider_message_id"],
    )
    op.create_foreign_key(
        "notifications_recipient_user_id_fkey",
        "notifications",
        "users",
        ["recipient_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        "notifications_order_id_fkey", "notifications", "orders", ["order_id"], ["id"]
    )


def downgrade():
    op.drop_constraint(
        "notifications_order_id_fkey", "notifications", type_="foreignkey"
    )
    op.drop_constraint(
        "notifications_recipient_user_id_fkey", "notifications", type_="foreignkey"
    )
    op.drop_constraint(
        "notifications_provider_message_id_key", "notifications", type_="unique"
    )
    op.drop_index(
        op.f("ix_notifications_recipient_user_id"), table_name="notifications"
    )
    op.drop_index(op.f("ix_notifications_order_id"), table_name="notifications")
    op.drop_column("notifications", "delivered_at")
    op.drop_column("notifications", "submitted_at")
    op.drop_column("notifications", "claimed_at")
    op.drop_column("notifications", "created_at")
    op.drop_column("notifications", "last_error")
    op.drop_column("notifications", "provider_message_id")
    op.drop_column("notifications", "event_type")
    op.drop_column("notifications", "order_id")
    op.drop_column("notifications", "recipient_user_id")
    op.drop_index(
        op.f("ix_sms_delivery_reports_provider_message_id"),
        table_name="sms_delivery_reports",
    )
    op.drop_table("sms_delivery_reports")
