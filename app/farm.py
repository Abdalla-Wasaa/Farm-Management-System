"""Flock biology and explicit, traceable conversion into saleable inventory."""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select

from app.auth import require
from app.models import (
    Business,
    BusinessMember,
    DailyRecord,
    Expense,
    Flock,
    Movement,
    Order,
    OrderItem,
    Payment,
    Product,
    ProductionTransfer,
    User,
)
from app.services import get_or_404, manages, quantity_for


def today():
    return datetime.now(ZoneInfo("Africa/Nairobi")).date()


def add_member(db, actor, business_id, user_id):
    require(actor, "admin")
    get_or_404(db, Business, business_id)
    user = get_or_404(db, User, user_id)
    require(user, "seller", "staff")
    previous = db.scalar(
        select(BusinessMember).where(
            BusinessMember.business_id == business_id, BusinessMember.user_id == user_id
        )
    )
    if previous:
        return previous
    member = BusinessMember(business_id=business_id, user_id=user_id)
    db.add(member)
    db.flush()
    return member


def create_flock(db, actor, data):
    manages(db, actor, data.business_id)
    if data.started_on > today():
        raise HTTPException(422, "Flock start date cannot be in the future")
    flock = Flock(**data.model_dump(), live_birds=data.initial_birds)
    db.add(flock)
    db.flush()
    return flock


def daily_record(db, actor, flock_id, data):
    flock = get_or_404(db, Flock, flock_id, lock=True)
    manages(db, actor, flock.business_id)
    if data.day < flock.started_on or data.day > today():
        raise HTTPException(422, "Daily record date outside flock lifetime")
    previous = db.scalar(
        select(DailyRecord).where(
            DailyRecord.flock_id == flock.id, DailyRecord.day == data.day
        )
    )
    if previous:
        if any(
            getattr(previous, key) != value for key, value in data.model_dump().items()
        ):
            raise HTTPException(
                409, "Daily record already exists with different values"
            )
        return previous
    if data.mortality > flock.live_birds:
        raise HTTPException(409, "Mortality exceeds live bird count")
    if flock.kind != "layer" and data.eggs:
        raise HTTPException(422, "Egg production requires a layer flock")
    flock.live_birds -= data.mortality
    record = DailyRecord(flock_id=flock.id, actor_id=actor.id, **data.model_dump())
    db.add(record)
    db.flush()
    return record


def transfer_production(db, actor, flock_id, data):
    # Lock flock before product consistently across all production actions.
    flock = get_or_404(db, Flock, flock_id, lock=True)
    manages(db, actor, flock.business_id)
    previous = db.scalar(
        select(ProductionTransfer).where(
            ProductionTransfer.flock_id == flock_id,
            ProductionTransfer.source == data.source,
        )
    )
    if previous:
        if any(getattr(previous, k) != v for k, v in data.model_dump().items()):
            raise HTTPException(409, "Production source reused with different values")
        return previous
    product = get_or_404(db, Product, data.product_id, lock=True)
    if product.business_id != flock.business_id:
        raise HTTPException(
            422, "Production and inventory must belong to the same business"
        )
    quantity_for(product, data.quantity)
    if product.category == "eggs":
        if flock.kind != "layer" or data.daily_record_id is None or data.birds_removed:
            raise HTTPException(
                422, "Egg transfers require a layer daily record and no bird removal"
            )
        if product.unit not in ("egg", "tray"):
            raise HTTPException(422, "Egg transfer unit must be egg or tray")
        record = get_or_404(db, DailyRecord, data.daily_record_id, lock=True)
        if record.flock_id != flock.id:
            raise HTTPException(422, "Daily record belongs to another flock")
        eggs = int(data.quantity * (30 if product.unit == "tray" else 1))
        if record.eggs - record.transferred_eggs < eggs:
            raise HTTPException(409, "Transfer exceeds untransferred eggs")
        record.transferred_eggs += eggs
    else:
        if data.daily_record_id is not None or data.birds_removed <= 0:
            raise HTTPException(
                422, "Bird harvest requires birds_removed and no egg record"
            )
        if (product.category == "live_broilers" and flock.kind != "broiler") or (
            product.category == "spent_layers" and flock.kind != "layer"
        ):
            raise HTTPException(422, "Product category does not match flock type")
        if product.unit not in ("bird", "kilogram"):
            raise HTTPException(422, "Bird harvest unit must be bird or kilogram")
        if product.unit == "bird" and data.quantity != data.birds_removed:
            raise HTTPException(422, "Bird quantity must equal removed birds")
        if data.birds_removed > flock.live_birds:
            raise HTTPException(409, "Harvest exceeds live birds")
        flock.live_birds -= data.birds_removed
    transfer = ProductionTransfer(
        flock_id=flock.id, actor_id=actor.id, **data.model_dump()
    )
    db.add(transfer)
    db.flush()
    product.stock += data.quantity
    db.add(
        Movement(
            product_id=product.id,
            actor_id=actor.id,
            kind="production",
            quantity=data.quantity,
            source=f"production:{transfer.id}",
        )
    )
    return transfer


def add_expense(db, actor, data):
    manages(db, actor, data.business_id)
    # Serialize expense-source retries per business.
    get_or_404(db, Business, data.business_id, lock=True)
    if data.flock_id is not None:
        flock = get_or_404(db, Flock, data.flock_id)
        if flock.business_id != data.business_id:
            raise HTTPException(422, "Flock belongs to another business")
    previous = db.scalar(
        select(Expense).where(
            Expense.business_id == data.business_id, Expense.source == data.source
        )
    )
    if previous:
        if any(getattr(previous, k) != v for k, v in data.model_dump().items()):
            raise HTTPException(409, "Expense source reused with different values")
        return previous
    expense = Expense(actor_id=actor.id, **data.model_dump())
    db.add(expense)
    db.flush()
    return expense


def summary(db, actor, business_id, start, end):
    manages(db, actor, business_id)
    if start > end:
        raise HTTPException(422, "Start must precede end")
    daily = (
        select(
            func.coalesce(func.sum(DailyRecord.mortality), 0),
            func.coalesce(func.sum(DailyRecord.eggs), 0),
            func.coalesce(func.sum(DailyRecord.feed_kg), 0),
        )
        .join(Flock)
        .where(Flock.business_id == business_id, DailyRecord.day.between(start, end))
    )
    mortality, eggs, feed = db.execute(daily).one()
    expenses = db.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(
            Expense.business_id == business_id, Expense.day.between(start, end)
        )
    )
    # Nairobi-local day boundaries include both endpoints.
    from datetime import time, timedelta

    lower = datetime.combine(start, time.min, ZoneInfo("Africa/Nairobi"))
    upper = datetime.combine(
        end + timedelta(days=1), time.min, ZoneInfo("Africa/Nairobi")
    )
    cash = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .join(Order)
        .where(
            Order.business_id == business_id,
            Payment.method == "cash",
            Payment.created_at >= lower,
            Payment.created_at < upper,
        )
    )
    sales = db.execute(
        select(
            OrderItem.unit, func.sum(OrderItem.quantity), func.sum(OrderItem.line_total)
        )
        .join(Order)
        .where(
            Order.business_id == business_id,
            Order.status.in_(["dispatched", "completed"]),
            Order.id.in_(
                select(Movement.order_id).where(
                    Movement.kind == "sale",
                    Movement.created_at >= lower,
                    Movement.created_at < upper,
                )
            ),
        )
        .group_by(OrderItem.unit)
    ).all()
    return {
        "currency": "KES",
        "start": start,
        "end": end,
        "mortality": mortality,
        "eggs": eggs,
        "feed_kg": feed,
        "expenses": expenses,
        "cash_received": cash,
        "cash_less_expenses": cash - expenses,
        "sales_by_unit": [
            {"unit": unit, "quantity": quantity, "item_revenue": revenue}
            for unit, quantity, revenue in sales
        ],
        "note": "Cash less expenses is not accounting profit. Delivery fees are included in cash, excluded from item revenue.",
    }
