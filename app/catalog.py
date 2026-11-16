"""User-administration and catalogue actions with explicit authorization."""

from fastapi import HTTPException

from app.auth import create_user, require
from app.models import Business, Product, User
from app.services import get_or_404, manages


def provision_user(db, actor, data):
    require(actor, "admin")
    return create_user(db, data.phone, data.password, data.role)


def create_business(db, actor, data):
    require(actor, "admin")
    owner = get_or_404(db, User, data.owner_id)
    if owner.role not in ("admin", "seller", "staff"):
        raise HTTPException(422, "Business owner must be seller, staff or admin")
    business = Business(**data.model_dump())
    db.add(business)
    db.flush()
    return business


def create_product(db, actor, data):
    manages(db, actor, data.business_id)
    product = Product(**data.model_dump())
    db.add(product)
    db.flush()
    return product


def update_product(db, actor, product_id, data):
    product = get_or_404(db, Product, product_id, lock=True)
    manages(db, actor, product.business_id)
    if data.business_id != product.business_id:
        raise HTTPException(422, "Products cannot be moved between businesses")
    for key, value in data.model_dump().items():
        setattr(product, key, value)
    db.flush()
    return product


def adjust_stock(db, actor, product_id, data):
    from sqlalchemy import select

    from app.models import Movement
    from app.services import quantity_for

    product = get_or_404(db, Product, product_id, lock=True)
    manages(db, actor, product.business_id)
    quantity_for(product, data.quantity)
    if data.quantity == 0:
        raise HTTPException(422, "Adjustment must be nonzero")
    source = f"adjust:{product_id}:{data.source}"
    previous = db.scalar(select(Movement).where(Movement.source == source))
    if previous:
        if previous.quantity != data.quantity:
            raise HTTPException(
                409, "Adjustment reference reused with a different quantity"
            )
        return product
    if product.stock + data.quantity < product.reserved:
        raise HTTPException(
            409, "Adjustment would consume reserved stock or make stock negative"
        )
    product.stock += data.quantity
    db.add(
        Movement(
            product_id=product.id,
            actor_id=actor.id,
            kind="adjustment",
            quantity=data.quantity,
            source=source,
        )
    )
    return product
