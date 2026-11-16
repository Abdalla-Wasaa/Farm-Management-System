"""Permission-checked business actions; callers provide one database transaction."""
import hashlib
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException
from sqlalchemy import select
from app.auth import require
from app.config import settings
from app.models import User, Business, Product, Order, OrderItem, Movement, Payment, Audit, Notification, now


def get_or_404(db, model, key, lock=False):
    row = db.scalar(select(model).where(model.id == key).with_for_update()) if lock else db.get(model, key)
    if row is None:
        raise HTTPException(404, f"{model.__name__} not found")
    return row


def manages(db, actor, business_id):
    business = get_or_404(db, Business, business_id)
    if actor.role != "admin" and not (actor.role in ("seller", "staff") and business.owner_id == actor.id):
        raise HTTPException(403, "This business belongs to another user")
    return business


def quantity_for(product, quantity):
    if product.unit != "kilogram" and quantity != quantity.to_integral_value():
        raise HTTPException(422, "Only kilogram quantities may be fractional")


def notify(db, order, event, user_id, text):
    key = f"order:{order.id}:{event}:user:{user_id}"
    if not db.scalar(select(Notification.id).where(Notification.event_key == key)):
        user = get_or_404(db, User, user_id)
        db.add(Notification(event_key=key, phone=user.phone, message=f"{order.reference}: {text}"))


def audit(db, order, actor, action):
    db.add(Audit(order_id=order.id, actor_id=actor.id if actor else None, action=action))


def add_stock(db, actor, product_id, data):
    product = get_or_404(db, Product, product_id, lock=True)
    manages(db, actor, product.business_id)
    quantity_for(product, data.quantity)
    source = f"manual:{product_id}:{data.source}"
    previous = db.scalar(select(Movement).where(Movement.source == source))
    if previous:
        if previous.quantity != data.quantity:
            raise HTTPException(409, "Stock source reused with different quantity")
        return product
    product.stock += data.quantity
    db.add(Movement(product_id=product.id, actor_id=actor.id, kind="receipt", quantity=data.quantity, source=source))
    return product


def place_order(db, actor, data, key):
    require(actor, "buyer")
    get_or_404(db, User, actor.id, lock=True)
    digest = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    previous = db.scalar(select(Order).where(Order.buyer_id == actor.id, Order.idempotency_key == key))
    if previous:
        if previous.request_hash != digest:
            raise HTTPException(409, "Idempotency key reused with different request")
        return previous
    items = sorted(data.items, key=lambda i: i.product_id)
    products = [get_or_404(db, Product, i.product_id, lock=True) for i in items]
    if len({p.business_id for p in products}) != 1:
        raise HTTPException(422, "One seller per order")
    for p, item in zip(products, items):
        quantity_for(p, item.quantity)
        if p.stock - p.reserved < item.quantity:
            raise HTTPException(409, "Insufficient stock")
    fee = settings.delivery_fee if data.fulfillment == "delivery" else Decimal(0)
    totals = [(p.price * i.quantity).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) for p, i in zip(products, items)]
    order = Order(reference="PF-" + uuid.uuid4().hex[:12].upper(), buyer_id=actor.id,
                  business_id=products[0].business_id, idempotency_key=key, request_hash=digest,
                  fulfillment=data.fulfillment, address=data.address, fee=fee, total=sum(totals, fee),
                  delivery_status="unassigned" if data.fulfillment == "delivery" else "not_required",
                  expires_at=now() + timedelta(minutes=settings.reservation_minutes))
    db.add(order)
    db.flush()
    for p, item, total in zip(products, items, totals):
        p.reserved += item.quantity
        db.add(OrderItem(order_id=order.id, product_id=p.id, name=p.name, description=p.description,
                         unit=p.unit, price=p.price, quantity=item.quantity, line_total=total))
        db.add(Movement(product_id=p.id, order_id=order.id, actor_id=actor.id, kind="reserve", quantity=item.quantity, source=f"reserve:{order.id}:{p.id}"))
    business = get_or_404(db, Business, order.business_id)
    notify(db, order, "new", business.owner_id, "New order received. Please confirm availability.")
    audit(db, order, actor, "created")
    return order


def stock_for_order(db, order, actor, release):
    items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.product_id)).all()
    for item in items:
        product = get_or_404(db, Product, item.product_id, lock=True)
        product.reserved -= item.quantity
        if not release:
            product.stock -= item.quantity
        kind = "release" if release else "sale"
        db.add(Movement(product_id=product.id, order_id=order.id, actor_id=actor.id if actor else None,
                        kind=kind, quantity=item.quantity, source=f"{kind}:{order.id}:{product.id}"))


def cancel(db, order, actor, expired=False):
    if order.status not in ("pending", "confirmed", "preparing", "ready") or order.delivery_status == "dispatched":
        raise HTTPException(409, "Order cannot be cancelled at this stage")
    if order.payment_status == "paid":
        raise HTTPException(409, "Paid orders require a refund workflow before cancellation")
    stock_for_order(db, order, actor, release=True)
    order.status = "expired" if expired else "cancelled"
    if order.fulfillment == "delivery":
        order.delivery_status = "cancelled"
    notify(db, order, "cancelled", order.buyer_id, "Order cancelled; reserved stock released.")
    audit(db, order, actor, order.status)


def transition(db, actor, order_id, target):
    order = get_or_404(db, Order, order_id, lock=True)
    if actor.role == "buyer":
        if order.buyer_id != actor.id or target != "cancelled":
            raise HTTPException(403, "Buyers may cancel only their own orders")
    else:
        manages(db, actor, order.business_id)
    if order.status == target:
        return order
    if target == "cancelled":
        cancel(db, order, actor)
        return order
    transitions = {"pending": "confirmed", "confirmed": "preparing", "preparing": "ready"}
    if target == "completed":
        if order.fulfillment != "pickup" or order.status != "ready":
            raise HTTPException(409, "Only ready pickup orders may be completed here")
        stock_for_order(db, order, actor, release=False)
    elif transitions.get(order.status) != target:
        raise HTTPException(409, "Invalid order transition")
    if order.status == "pending" and order.expires_at <= now():
        raise HTTPException(409, "Reservation expired")
    order.status = target
    audit(db, order, actor, target)
    if target == "confirmed":
        notify(db, order, target, order.buyer_id, f"Order confirmed. Total KES {order.total:.2f}.")
    return order


def assign_rider(db, actor, order_id, rider_id):
    require(actor, "admin")
    order = get_or_404(db, Order, order_id, lock=True)
    rider = get_or_404(db, User, rider_id)
    if rider.role != "rider":
        raise HTTPException(422, "Assigned user must be a rider")
    if order.fulfillment != "delivery" or order.status not in ("confirmed", "preparing", "ready") or order.delivery_status not in ("unassigned", "assigned"):
        raise HTTPException(409, "Order cannot be assigned")
    if order.rider_id is not None and order.rider_id != rider.id:
        raise HTTPException(409, "Rider already assigned")
    order.rider_id = rider.id
    order.delivery_status = "assigned"
    audit(db, order, actor, f"assigned:{rider.id}")
    notify(db, order, "assigned", rider.id, "Delivery assigned. Check your assigned deliveries for details.")
    return order


def progress_delivery(db, actor, order_id, target):
    require(actor, "rider")
    order = get_or_404(db, Order, order_id, lock=True)
    if order.rider_id != actor.id:
        raise HTTPException(403, "Delivery assigned to another rider")
    if order.delivery_status == target:
        return order
    if target == "dispatched":
        if order.status != "ready" or order.delivery_status != "assigned":
            raise HTTPException(409, "Order must be ready and assigned")
        stock_for_order(db, order, actor, release=False)
        order.status = "dispatched"
    elif target == "delivered":
        if order.delivery_status != "dispatched" or order.status != "dispatched":
            raise HTTPException(409, "Order must be dispatched")
        order.status = "completed"
    else:
        raise HTTPException(422, "Invalid delivery status")
    order.delivery_status = target
    audit(db, order, actor, target)
    notify(db, order, target, order.buyer_id, "Order dispatched." if target == "dispatched" else "Order delivered. Thank you.")
    return order


def record_payment(db, actor, order_id, data):
    """Cash receipt boundary; future verified provider callbacks use a separate adapter."""
    order = get_or_404(db, Order, order_id, lock=True)
    if actor.role == "rider":
        if order.rider_id != actor.id or order.delivery_status != "delivered":
            raise HTTPException(403, "Rider may record cash only after their delivery")
    else:
        manages(db, actor, order.business_id)
    previous = db.scalar(select(Payment).where(Payment.order_id == order.id))
    if previous:
        if previous.receipt == data.receipt and previous.amount == data.amount:
            return previous
        raise HTTPException(409, "Payment already recorded")
    if order.status != "completed" or data.amount != order.total:
        raise HTTPException(409, "Record exact cash total after pickup or delivery completion")
    if db.scalar(select(Payment.id).where(Payment.receipt == data.receipt)):
        raise HTTPException(409, "Receipt already used")
    payment = Payment(order_id=order.id, actor_id=actor.id, amount=data.amount, receipt=data.receipt)
    db.add(payment)
    order.payment_status = "paid"
    audit(db, order, actor, "cash_received")
    notify(db, order, "paid", order.buyer_id, f"Cash payment received: KES {data.amount:.2f}.")
    db.flush()
    return payment


def view_order(db, actor, order_id):
    order = get_or_404(db, Order, order_id)
    if actor.role == "buyer" and order.buyer_id == actor.id:
        return order
    if actor.role == "rider" and order.rider_id == actor.id:
        return order
    manages(db, actor, order.business_id)
    return order


def expire_orders(db):
    orders = db.scalars(select(Order).where(Order.status == "pending", Order.expires_at <= now()).order_by(Order.id).with_for_update(skip_locked=True)).all()
    for order in orders:
        cancel(db, order, None, expired=True)
    return len(orders)
