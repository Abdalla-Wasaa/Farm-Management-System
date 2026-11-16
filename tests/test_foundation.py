import pytest

from app.auth import passwords
from app.schemas import Register, phone_number


@pytest.mark.parametrize(
    "raw", ["0712345678", "254712345678", "+254712345678", "0712 345 678"]
)
def test_phone(raw):
    assert phone_number(raw) == "+254712345678"


@pytest.mark.parametrize("raw", ["+15551234567", "070", "+254212345678"])
def test_bad_phone(raw):
    with pytest.raises(ValueError):
        phone_number(raw)


def test_registration_and_password():
    with pytest.raises(ValueError):
        Register(phone="0712345678", password="longpassword123", role="admin")
    hashed = passwords.hash("longpassword123")
    assert passwords.verify("longpassword123", hashed)
    assert not passwords.verify("wrong", hashed)


def test_password_whitespace_is_preserved():
    password = "  a-long-password  "
    assert Register(phone="0712345678", password=password).password == password
