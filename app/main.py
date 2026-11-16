from typing import Annotated
from fastapi import FastAPI, Depends, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app import schemas as s, services as svc
from app.auth import current_user, require, create_user, passwords, token, DUMMY_HASH
from app.config import settings
from app.db import get_db
from app.models import User, Business, Product, Order, OrderItem, Payment, Audit, Movement, Notification, NotificationAttempt

app = FastAPI(title="Poultry Farm & Marketplace", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])
DB = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(current_user)]

@app.exception_handler(IntegrityError)
def conflict(request, exc):
    return JSONResponse(status_code=409, content={"detail": "Conflicting record or invalid database constraint"})


def row(obj):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def product_view(product):
    data = row(product)
    data["available"] = product.stock - product.reserved
    data["currency"] = "KES"
    return data


def order_view(db, order):
    data = row(order)
    data.pop("request_hash")
    data.pop("idempotency_key")
    data["items"] = [row(i) for i in db.scalars(select(OrderItem).where(OrderItem.order_id == order.id))]
    data["payments"] = [row(p) for p in db.scalars(select(Payment).where(Payment.order_id == order.id))]
    return data

@app.get('/health')
def health(db: DB):
    db.execute(text('SELECT 1'))
    return {"status": "ok"}

@app.post('/auth/register', status_code=201)
def register(data: s.Register, db: DB):
    user = create_user(db, data.phone, data.password)
    return {"id": user.id, "phone": user.phone, "role": user.role}

@app.post('/auth/login')
def login(data: s.Login, db: DB):
    user = db.scalar(select(User).where(User.phone == data.phone))
    valid = passwords.verify(data.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        raise HTTPException(401, "Invalid phone or password")
    return {"access_token": token(user), "token_type": "bearer"}

@app.get('/users/me')
def me(actor: Actor):
    return {"id": actor.id, "phone": actor.phone, "role": actor.role}

@app.post('/admin/users', status_code=201)
def privileged_user(data: s.PrivilegedUser, db: DB, actor: Actor):
    require(actor, "admin")
    user = create_user(db, data.phone, data.password, data.role)
    return {"id": user.id, "phone": user.phone, "role": user.role}

@app.post('/businesses', status_code=201)
def create_business(data: s.BusinessIn, db: DB, actor: Actor):
    require(actor, "admin")
    owner = svc.get_or_404(db, User, data.owner_id)
    if owner.role not in ("admin", "seller", "staff"):
        raise HTTPException(422, "Business owner must be seller, staff or admin")
    business = Business(**data.model_dump())
    db.add(business)
    db.flush()
    return row(business)

@app.get('/businesses')
def businesses(db: DB, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    return [row(b) for b in db.scalars(select(Business).order_by(Business.id).offset(offset).limit(limit))]

@app.post('/products', status_code=201)
def create_product(data: s.ProductIn, db: DB, actor: Actor):
    svc.manages(db, actor, data.business_id)
    product = Product(**data.model_dump())
    db.add(product)
    db.flush()
    return product_view(product)

@app.get('/products')
def products(db: DB, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    return [product_view(p) for p in db.scalars(select(Product).order_by(Product.id).offset(offset).limit(limit))]

@app.get('/products/{product_id}')
def product(product_id: int, db: DB):
    return product_view(svc.get_or_404(db, Product, product_id))

@app.post('/products/{product_id}/stock')
def stock(product_id: int, data: s.StockIn, db: DB, actor: Actor):
    return product_view(svc.add_stock(db, actor, product_id, data))

@app.get('/products/{product_id}/movements')
def movements(product_id: int, db: DB, actor: Actor):
    product = svc.get_or_404(db, Product, product_id)
    svc.manages(db, actor, product.business_id)
    return [row(m) for m in db.scalars(select(Movement).where(Movement.product_id == product_id).order_by(Movement.id).limit(500))]

@app.post('/orders', status_code=201)
def create_order(data: s.OrderIn, db: DB, actor: Actor,
                 idempotency_key: Annotated[str, Header(min_length=1, max_length=100)]):
    return order_view(db, svc.place_order(db, actor, data, idempotency_key))

@app.get('/orders')
def my_orders(db: DB, actor: Actor, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    query = select(Order)
    if actor.role == "buyer":
        query = query.where(Order.buyer_id == actor.id)
    elif actor.role == "rider":
        query = query.where(Order.rider_id == actor.id)
    elif actor.role != "admin":
        query = query.join(Business).where(Business.owner_id == actor.id)
    return [order_view(db, o) for o in db.scalars(query.order_by(Order.id.desc()).offset(offset).limit(limit))]

@app.get('/orders/{order_id}')
def order(order_id: int, db: DB, actor: Actor):
    return order_view(db, svc.view_order(db, actor, order_id))

@app.post('/orders/{order_id}/status')
def order_status(order_id: int, data: s.Transition, db: DB, actor: Actor):
    return order_view(db, svc.transition(db, actor, order_id, data.status))

@app.post('/orders/{order_id}/rider')
def rider(order_id: int, data: s.Assignment, db: DB, actor: Actor):
    return order_view(db, svc.assign_rider(db, actor, order_id, data.rider_id))

@app.get('/deliveries/assigned')
def assigned(db: DB, actor: Actor):
    require(actor, "rider")
    return [order_view(db, o) for o in db.scalars(select(Order).where(Order.rider_id == actor.id).order_by(Order.id.desc()).limit(100))]

@app.post('/orders/{order_id}/delivery')
def delivery(order_id: int, data: s.DeliveryIn, db: DB, actor: Actor):
    return order_view(db, svc.progress_delivery(db, actor, order_id, data.status))

@app.post('/orders/{order_id}/payments', status_code=201)
def payment(order_id: int, data: s.PaymentIn, db: DB, actor: Actor):
    return row(svc.record_payment(db, actor, order_id, data))

@app.get('/orders/{order_id}/audit')
def order_audit(order_id: int, db: DB, actor: Actor):
    order = svc.get_or_404(db, Order, order_id)
    svc.manages(db, actor, order.business_id)
    return [row(a) for a in db.scalars(select(Audit).where(Audit.order_id == order_id).order_by(Audit.id))]

@app.get('/admin/notifications')
def notifications(db: DB, actor: Actor):
    require(actor, "admin")
    # Exclude recipient phone and message contents from operational views.
    return [{"id": n.id, "event_key": n.event_key, "status": n.status, "attempts": n.attempts,
             "next_attempt": n.next_attempt,
             "history": [row(a) for a in db.scalars(select(NotificationAttempt).where(NotificationAttempt.notification_id == n.id))]}
            for n in db.scalars(select(Notification).order_by(Notification.id.desc()).limit(100))]
