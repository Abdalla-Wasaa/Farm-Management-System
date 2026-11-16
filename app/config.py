from decimal import Decimal
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://farm:farm@localhost:5432/farm"
    jwt_secret: str = Field(min_length=32)
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    farm_name: str = "My Poultry Farm"
    delivery_fee: Decimal = Field(default=Decimal("200.00"), ge=0, decimal_places=2)
    reservation_minutes: int = Field(default=60, ge=1)
    sms_mode: Literal["dry-run", "sandbox", "live"] = "dry-run"
    at_username: str = "sandbox"
    at_api_key: str = ""
    at_sender_id: str = ""
    sms_allowed_recipients: list[str] = []
    sms_transactional_approved: bool = False
    sms_delivery_token: SecretStr = SecretStr("")
    sms_max_attempts: int = Field(default=5, ge=1, le=10)
    sms_claim_seconds: int = Field(default=120, ge=30, le=600)

    @field_validator("sms_allowed_recipients")
    @classmethod
    def normalize_sms_recipients(cls, values):
        from app.schemas import phone_number

        return list(dict.fromkeys(phone_number(value) for value in values))

    daraja_mode: Literal["disabled", "sandbox"] = "disabled"
    daraja_consumer_key: SecretStr = SecretStr("")
    daraja_consumer_secret: SecretStr = SecretStr("")
    daraja_passkey: SecretStr = SecretStr("")
    daraja_shortcode: str = "174379"
    daraja_callback_url: str = ""


settings = Settings()
