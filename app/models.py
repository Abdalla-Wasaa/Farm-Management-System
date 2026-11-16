from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(13), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="buyer")
    __table_args__ = (
        CheckConstraint("role in ('buyer','seller','staff','rider','admin')"),
    )


class Business(Base):
    __tablename__ = "businesses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(2000), default="")
    category: Mapped[str] = mapped_column(String(30))
    unit: Mapped[str] = mapped_column(String(15))
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    stock: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    reserved: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    __table_args__ = (
        CheckConstraint("stock >= 0 AND reserved >= 0 AND stock >= reserved"),
        CheckConstraint("price > 0"),
        CheckConstraint(
            "category in ('eggs','live_broilers','dressed_chicken','spent_layers')"
        ),
        CheckConstraint("unit in ('bird','kilogram','egg','tray')"),
    )


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(20), unique=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    payment_status: Mapped[str] = mapped_column(String(20), default="unpaid")
    delivery_status: Mapped[str] = mapped_column(String(20), default="not_required")
    fulfillment: Mapped[str] = mapped_column(String(10))
    address: Mapped[str] = mapped_column(String(500), default="")
    fee: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    rider_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("buyer_id", "idempotency_key"),
        CheckConstraint(
            "status in ('pending','confirmed','preparing','ready','dispatched','completed','cancelled','expired')",
            name="ck_order_status",
        ),
        CheckConstraint("payment_status in ('unpaid','paid')", name="ck_order_payment"),
        CheckConstraint(
            "delivery_status in ('not_required','unassigned','assigned','dispatched','delivered','cancelled')",
            name="ck_order_delivery",
        ),
        CheckConstraint(
            "fulfillment in ('pickup','delivery') AND currency = 'KES' AND total >= fee AND fee >= 0",
            name="ck_order_values",
        ),
        Index("ix_orders_expiry", "status", "expires_at"),
        Index("ix_orders_buyer", "buyer_id"),
        Index("ix_orders_rider", "rider_id"),
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(2000))
    unit: Mapped[str] = mapped_column(String(15))
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    __table_args__ = (
        CheckConstraint(
            "quantity > 0 AND price > 0 AND line_total >= 0", name="ck_item_values"
        ),
        Index("ix_order_items_order", "order_id"),
    )


class Movement(Base):
    __tablename__ = "inventory_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    source: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    method: Mapped[str] = mapped_column(String(20), default="cash")
    receipt: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (
        CheckConstraint(
            "amount > 0 AND method in ('cash','mpesa_sandbox')", name="ck_cash_payment"
        ),
    )


class Audit(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String(150), unique=True)
    recipient_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)
    event_type: Mapped[str | None] = mapped_column(String(30))
    provider_message_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    last_error: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, server_default=func.now()
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    phone: Mapped[str] = mapped_column(String(13))
    message: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (Index("ix_notification_queue", "status", "next_attempt"),)


class NotificationAttempt(Base):
    __tablename__ = "notification_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id"))
    outcome: Mapped[str] = mapped_column(String(30))
    provider_response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BusinessMember(Base):
    __tablename__ = "business_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (UniqueConstraint("business_id", "user_id"),)


class Flock(Base):
    __tablename__ = "flocks"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10))
    initial_birds: Mapped[int]
    live_birds: Mapped[int]
    started_on: Mapped[date] = mapped_column(Date)
    __table_args__ = (
        CheckConstraint("kind in ('broiler','layer')"),
        CheckConstraint(
            "initial_birds > 0 AND live_birds >= 0 AND live_birds <= initial_birds"
        ),
    )


class DailyRecord(Base):
    __tablename__ = "daily_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    flock_id: Mapped[int] = mapped_column(ForeignKey("flocks.id"))
    day: Mapped[date] = mapped_column(Date)
    mortality: Mapped[int]
    eggs: Mapped[int]
    feed_kg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    transferred_eggs: Mapped[int] = mapped_column(default=0)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (
        UniqueConstraint("flock_id", "day"),
        CheckConstraint(
            "mortality >= 0 AND eggs >= 0 AND feed_kg >= 0 AND transferred_eggs >= 0 AND transferred_eggs <= eggs"
        ),
    )


class ProductionTransfer(Base):
    __tablename__ = "production_transfers"
    id: Mapped[int] = mapped_column(primary_key=True)
    flock_id: Mapped[int] = mapped_column(ForeignKey("flocks.id"))
    daily_record_id: Mapped[int | None] = mapped_column(ForeignKey("daily_records.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    birds_removed: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("flock_id", "source"),
        CheckConstraint("quantity > 0 AND birds_removed >= 0"),
    )


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    flock_id: Mapped[int | None] = mapped_column(ForeignKey("flocks.id"))
    day: Mapped[date] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(String(500))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    source: Mapped[str] = mapped_column(String(100))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (
        UniqueConstraint("business_id", "source"),
        CheckConstraint("amount > 0"),
    )


class MpesaIntent(Base):
    __tablename__ = "mpesa_intents"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    buyer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(13))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    checkout_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    merchant_id: Mapped[str | None] = mapped_column(String(80))
    result_code: Mapped[str | None] = mapped_column(String(30))
    checks: Mapped[int] = mapped_column(default=0)
    next_check: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("order_id", "idempotency_key"),
        CheckConstraint(
            "status in ('queued','submitting','pending','uncertain','failed','succeeded')",
            name="ck_mpesa_intent_status",
        ),
        CheckConstraint("amount > 0", name="ck_mpesa_intent_amount"),
        Index("ix_mpesa_intents_queue", "status", "next_check"),
    )


class SmsDeliveryReport(Base):
    __tablename__ = "sms_delivery_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_message_id: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(13))
    failure_reason: Mapped[str | None] = mapped_column(String(80))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("provider_message_id", "status"),)
