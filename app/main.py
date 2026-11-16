from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import catalog, farm
from app import schemas as s
from app import services as svc
from app.auth import DUMMY_HASH, create_user, current_user, passwords, require, token
from app.config import settings
from app.db import get_db
from app.models import (
    Audit,
    Business,
    BusinessMember,
    DailyRecord,
    Expense,
    Flock,
    Movement,
    Notification,
    NotificationAttempt,
    Order,
    OrderItem,
    Payment,
    Product,
    ProductionTransfer,
    User,
)

app = FastAPI(title="Poultry Farm & Marketplace", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)
DB = Annotated[Session, Depends(get_db, scope="function")]
Actor = Annotated[User, Depends(current_user)]


@app.exception_handler(IntegrityError)
def conflict(request, exc):
    return JSONResponse(
        status_code=409,
        content={"detail": "Conflicting record or invalid database constraint"},
    )


def row(obj):
    return jsonable_encoder(
        {c.name: getattr(obj, c.name) for c in obj.__table__.columns},
        custom_encoder={Decimal: str},
    )


def product_view(product):
    data = row(product)
    data["available"] = str(product.stock - product.reserved)
    data["currency"] = "KES"
    return data


def order_view(db, order):
    data = row(order)
    data.pop("request_hash")
    data.pop("idempotency_key")
    data["items"] = [
        row(i)
        for i in db.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ]
    data["payments"] = [
        row(p) for p in db.scalars(select(Payment).where(Payment.order_id == order.id))
    ]
    return data


@app.get("/health")
def health(db: DB):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/auth/register", status_code=201)
def register(data: s.Register, db: DB):
    user = create_user(db, data.phone, data.password)
    return {"id": user.id, "phone": user.phone, "role": user.role}


@app.post("/auth/login")
def login(data: s.Login, db: DB):
    user = db.scalar(select(User).where(User.phone == data.phone))
    valid = passwords.verify(data.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        raise HTTPException(401, "Invalid phone or password")
    return {"access_token": token(user), "token_type": "bearer"}


@app.get("/users/me")
def me(actor: Actor):
    return {"id": actor.id, "phone": actor.phone, "role": actor.role}


@app.post("/admin/users", status_code=201)
def privileged_user(data: s.PrivilegedUser, db: DB, actor: Actor):
    user = catalog.provision_user(db, actor, data)
    return {"id": user.id, "phone": user.phone, "role": user.role}


@app.post("/businesses", status_code=201)
def create_business(data: s.BusinessIn, db: DB, actor: Actor):
    return row(catalog.create_business(db, actor, data))


@app.get("/businesses")
def businesses(
    db: DB, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
):
    return [
        row(b)
        for b in db.scalars(
            select(Business).order_by(Business.id).offset(offset).limit(limit)
        )
    ]


@app.post("/products", status_code=201)
def create_product(data: s.ProductIn, db: DB, actor: Actor):
    return product_view(catalog.create_product(db, actor, data))


@app.get("/products")
def products(
    db: DB, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
):
    return [
        product_view(p)
        for p in db.scalars(
            select(Product).order_by(Product.id).offset(offset).limit(limit)
        )
    ]


@app.get("/products/{product_id}")
def product(product_id: int, db: DB):
    return product_view(svc.get_or_404(db, Product, product_id))


@app.post("/products/{product_id}/stock")
def stock(product_id: int, data: s.StockIn, db: DB, actor: Actor):
    return product_view(svc.add_stock(db, actor, product_id, data))


@app.get("/products/{product_id}/movements")
def movements(product_id: int, db: DB, actor: Actor):
    product = svc.get_or_404(db, Product, product_id)
    svc.manages(db, actor, product.business_id)
    return [
        row(m)
        for m in db.scalars(
            select(Movement)
            .where(Movement.product_id == product_id)
            .order_by(Movement.id)
            .limit(500)
        )
    ]


@app.post("/orders", status_code=201)
def create_order(
    data: s.OrderIn,
    db: DB,
    actor: Actor,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=100)],
):
    return order_view(db, svc.place_order(db, actor, data, idempotency_key))


@app.get("/orders")
def my_orders(
    db: DB,
    actor: Actor,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    query = select(Order)
    if actor.role == "buyer":
        query = query.where(Order.buyer_id == actor.id)
    elif actor.role == "rider":
        query = query.where(Order.rider_id == actor.id)
    elif actor.role != "admin":
        query = query.join(Business).where(
            or_(
                Business.owner_id == actor.id,
                Business.id.in_(
                    select(BusinessMember.business_id).where(
                        BusinessMember.user_id == actor.id
                    )
                ),
            )
        )
    return [
        order_view(db, o)
        for o in db.scalars(query.order_by(Order.id.desc()).offset(offset).limit(limit))
    ]


@app.get("/orders/{order_id}")
def order(order_id: int, db: DB, actor: Actor):
    return order_view(db, svc.view_order(db, actor, order_id))


@app.post("/orders/{order_id}/status")
def order_status(order_id: int, data: s.Transition, db: DB, actor: Actor):
    return order_view(db, svc.transition(db, actor, order_id, data.status))


@app.post("/orders/{order_id}/rider")
def rider(order_id: int, data: s.Assignment, db: DB, actor: Actor):
    return order_view(db, svc.assign_rider(db, actor, order_id, data.rider_id))


@app.get("/deliveries/assigned")
def assigned(db: DB, actor: Actor):
    require(actor, "rider")
    return [
        order_view(db, o)
        for o in db.scalars(
            select(Order)
            .where(Order.rider_id == actor.id)
            .order_by(Order.id.desc())
            .limit(100)
        )
    ]


@app.post("/orders/{order_id}/delivery")
def delivery(order_id: int, data: s.DeliveryIn, db: DB, actor: Actor):
    return order_view(db, svc.progress_delivery(db, actor, order_id, data.status))


@app.post("/orders/{order_id}/payments", status_code=201)
def payment(order_id: int, data: s.PaymentIn, db: DB, actor: Actor):
    return row(svc.record_payment(db, actor, order_id, data))


@app.get("/orders/{order_id}/audit")
def order_audit(order_id: int, db: DB, actor: Actor):
    order = svc.get_or_404(db, Order, order_id)
    svc.manages(db, actor, order.business_id)
    return [
        row(a)
        for a in db.scalars(
            select(Audit).where(Audit.order_id == order_id).order_by(Audit.id)
        )
    ]


@app.get("/admin/notifications")
def notifications(db: DB, actor: Actor):
    require(actor, "admin")
    # Exclude recipient phone and message contents from operational views.
    return [
        {
            "id": n.id,
            "event_key": n.event_key,
            "status": n.status,
            "attempts": n.attempts,
            "next_attempt": n.next_attempt,
            "history": [
                row(a)
                for a in db.scalars(
                    select(NotificationAttempt).where(
                        NotificationAttempt.notification_id == n.id
                    )
                )
            ],
        }
        for n in db.scalars(
            select(Notification).order_by(Notification.id.desc()).limit(100)
        )
    ]


@app.post("/businesses/{business_id}/members", status_code=201)
def business_member(business_id: int, data: s.MemberIn, db: DB, actor: Actor):
    return row(farm.add_member(db, actor, business_id, data.user_id))


@app.post("/flocks", status_code=201)
def create_flock(data: s.FlockIn, db: DB, actor: Actor):
    return row(farm.create_flock(db, actor, data))


@app.get("/businesses/{business_id}/flocks")
def flocks(business_id: int, db: DB, actor: Actor):
    svc.manages(db, actor, business_id)
    return [
        row(f)
        for f in db.scalars(
            select(Flock)
            .where(Flock.business_id == business_id)
            .order_by(Flock.id)
            .limit(500)
        )
    ]


@app.post("/flocks/{flock_id}/daily-records", status_code=201)
def daily_record(flock_id: int, data: s.DailyIn, db: DB, actor: Actor):
    return row(farm.daily_record(db, actor, flock_id, data))


@app.get("/flocks/{flock_id}/daily-records")
def daily_records(flock_id: int, db: DB, actor: Actor):
    flock = svc.get_or_404(db, Flock, flock_id)
    svc.manages(db, actor, flock.business_id)
    return [
        row(r)
        for r in db.scalars(
            select(DailyRecord)
            .where(DailyRecord.flock_id == flock_id)
            .order_by(DailyRecord.day.desc())
            .limit(500)
        )
    ]


@app.post("/flocks/{flock_id}/transfers", status_code=201)
def transfer(flock_id: int, data: s.TransferIn, db: DB, actor: Actor):
    return row(farm.transfer_production(db, actor, flock_id, data))


@app.get("/flocks/{flock_id}/transfers")
def transfers(flock_id: int, db: DB, actor: Actor):
    flock = svc.get_or_404(db, Flock, flock_id)
    svc.manages(db, actor, flock.business_id)
    return [
        row(t)
        for t in db.scalars(
            select(ProductionTransfer)
            .where(ProductionTransfer.flock_id == flock_id)
            .order_by(ProductionTransfer.id.desc())
            .limit(500)
        )
    ]


@app.post("/expenses", status_code=201)
def expense(data: s.ExpenseIn, db: DB, actor: Actor):
    return row(farm.add_expense(db, actor, data))


@app.get("/businesses/{business_id}/expenses")
def expenses(business_id: int, db: DB, actor: Actor):
    svc.manages(db, actor, business_id)
    return [
        row(e)
        for e in db.scalars(
            select(Expense)
            .where(Expense.business_id == business_id)
            .order_by(Expense.day.desc())
            .limit(500)
        )
    ]


@app.get("/businesses/{business_id}/summary")
def business_summary(business_id: int, start: date, end: date, db: DB, actor: Actor):
    return jsonable_encoder(
        farm.summary(db, actor, business_id, start, end), custom_encoder={Decimal: str}
    )


@app.post("/orders/{order_id}/payments/mpesa", status_code=202)
def mpesa_payment(
    order_id: int,
    data: s.MpesaIn,
    db: DB,
    actor: Actor,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=100)],
):
    from app.payments import request_stk

    intent = request_stk(db, actor, order_id, data, idempotency_key)
    return {
        "id": intent.id,
        "status": intent.status,
        "environment": "sandbox",
        "amount": str(intent.amount),
    }


@app.get("/orders/{order_id}/payments/mpesa")
def mpesa_status(order_id: int, db: DB, actor: Actor):
    from app.models import MpesaIntent

    svc.view_order(db, actor, order_id)
    return [
        {
            "id": i.id,
            "status": i.status,
            "amount": str(i.amount),
            "environment": "sandbox",
            "checkout_id": i.checkout_id,
            "result_code": i.result_code,
            "checks": i.checks,
        }
        for i in db.scalars(
            select(MpesaIntent)
            .where(MpesaIntent.order_id == order_id)
            .order_by(MpesaIntent.id)
        )
    ]


@app.post("/payments/mpesa/callback")
def mpesa_callback(data: s.MpesaCallback, db: DB):
    from app.payments import callback_hint

    return callback_hint(db, data)
