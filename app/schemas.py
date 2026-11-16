import re
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Money = Decimal

def phone_number(value: str) -> str:
    value = re.sub(r"[\s()-]", "", value)
    if value.startswith("0"):
        value = "+254" + value[1:]
    elif value.startswith("254"):
        value = "+" + value
    if not re.fullmatch(r"\+254[17]\d{8}", value):
        raise ValueError("Use a Kenyan mobile number, e.g. +254712345678")
    return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class Register(Input):
    phone: str
    password: str = Field(min_length=12, max_length=128)
    _phone = field_validator("phone")(phone_number)

class Login(Input):
    phone: str
    password: str = Field(max_length=128)
    _phone = field_validator("phone")(phone_number)

class PrivilegedUser(Register):
    role: Literal["seller", "staff", "rider", "admin"]

class BusinessIn(Input):
    name: str = Field(min_length=1, max_length=120)
    owner_id: int

class ProductIn(Input):
    business_id: int
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    category: Literal["eggs", "live_broilers", "dressed_chicken", "spent_layers"]
    unit: Literal["bird", "kilogram", "egg", "tray"]
    price: Decimal = Field(gt=0, max_digits=14, decimal_places=2)

class StockIn(Input):
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    source: str = Field(min_length=1, max_length=100)

class ItemIn(Input):
    product_id: int
    quantity: Decimal = Field(gt=0, max_digits=10, decimal_places=3)

class OrderIn(Input):
    items: list[ItemIn] = Field(min_length=1, max_length=100)
    fulfillment: Literal["pickup", "delivery"]
    address: str = Field(default="", max_length=500)
    @model_validator(mode="after")
    def validate_items(self):
        if len({i.product_id for i in self.items}) != len(self.items):
            raise ValueError("Combine repeated products into one item")
        if self.fulfillment == "delivery" and not self.address:
            raise ValueError("Delivery requires an address")
        return self

class Transition(Input):
    status: Literal["confirmed", "preparing", "ready", "cancelled", "completed"]

class Assignment(Input):
    rider_id: int

class DeliveryIn(Input):
    status: Literal["dispatched", "delivered"]

class PaymentIn(Input):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    receipt: str = Field(min_length=1, max_length=100)
