from decimal import Decimal
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://farm:farm@localhost:5432/farm"
    jwt_secret: str = Field(min_length=32)
    cors_origins: list[str] = ["http://localhost:5173"]
    farm_name: str = "My Poultry Farm"
    delivery_fee: Decimal = Field(default=Decimal("200.00"), ge=0, decimal_places=2)
    reservation_minutes: int = Field(default=60, ge=1)
    sms_mode: Literal["dry-run", "sandbox", "live"] = "dry-run"
    at_username: str = "sandbox"
    at_api_key: str = ""
    at_sender_id: str = ""

settings = Settings()
