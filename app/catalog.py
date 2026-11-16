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
