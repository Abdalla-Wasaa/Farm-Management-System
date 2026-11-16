# Poultry farm and marketplace backend

FastAPI modular monolith for Kenya; PostgreSQL is required. OpenAPI: `/docs`.

## Local setup

Python 3.12+, Docker Compose:

```sh
cp .env.example .env
# Set JWT_SECRET to a random 32+ character secret; set POSTGRES_PASSWORD.
# DATABASE_URL is used by host commands. Match its password to POSTGRES_PASSWORD.
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
docker compose up -d db
alembic upgrade head
python -m app.cli create-admin --phone 0712345678
uvicorn app.main:app --reload
# In another terminal with the virtualenv active:
python -m app.worker
```

Alternatively `docker compose up --build -d` runs migrations, API and worker.
Create admin using `docker compose exec api python -m app.cli create-admin --phone 0712345678`.
First administrator creation seeds your farm (FARM_NAME). Password input is hidden.
Privileged accounts are created by an admin at `POST /admin/users`, never public registration.

## Ordering rules

All prices are KES decimals; only kilogram quantities may be fractional. One seller per order.
Send a unique `Idempotency-Key` on order creation and reuse it on network retries.
Stock is reserved on order placement; pending reservations expire after 60 minutes by default.
Confirmation accepts the reservation; confirmed orders do not auto-expire. Cancellation before
handover releases stock. Sale consumes stock at dispatch or pickup completion.
Transitions: pending → confirmed → preparing → ready → completed (pickup), or ready → dispatched
→ completed (delivery). Only the assigned rider can dispatch/deliver. Admin assigns the rider.
Delivery fee is a fixed, server-configured KES fee (default 200), not a routing quote.
Cash receipts are authorized attestations of physical cash collection, after completion only,
for the exact total. Receipts and recording actor/time are retained separately from orders.
There is **no M-Pesa/Daraja integration**. Future provider callbacks must verify payment independently;
`app.services.record_payment` is the cash boundary, not a generic unverified success webhook.

## SMS

Default `SMS_MODE=dry-run` persists attempts without contacting a provider. Worker runs both
reservation expiry and the transactional notification outbox; SMS failures never undo orders.
Set `SMS_MODE=sandbox`, `AT_USERNAME=sandbox`, and a sandbox API key to use Africa's Talking's
sandbox simulator. Use the simulator's configured test mobile numbers. Sandbox is not live SMS.
Live requires explicitly setting `SMS_MODE=live`, your live username/key, and optionally an approved
sender ID. Keep credentials in `.env`, never Git. Templates omit full addresses.

The worker records sanitized provider status/message IDs, not complete response bodies (which can
contain recipient numbers). HTTP 429/5xx, transport errors and malformed responses retry with capped
exponential backoff, at most 5 attempts. Other rejected responses fail permanently. Operational
status/attempt history is available to admins at `/admin/notifications`.
Unique event keys prevent duplicate logical notifications. Provider submission is not proof of handset
delivery. There is no delivery-report webhook yet. A crash after provider acceptance and before DB
commit, or an ambiguous timeout, can result in a duplicate SMS: Africa's Talking has no client
idempotency guarantee here. This MVP provides at-least-once submission, not exactly-once delivery.
Dry-run events are terminal and are never automatically replayed as live messages.

Provider reference: https://help.africastalking.com/en/articles/742491-why-did-my-messages-fail

## Tests

Use a **dedicated** database ending `_test`; test fixtures truncate it. Never use a shared database.

```sh
createdb -h localhost -U farm farm_test
DATABASE_URL=postgresql+psycopg://farm:YOUR_PASSWORD@localhost:5432/farm_test alembic upgrade head
DATABASE_URL=postgresql+psycopg://farm:YOUR_PASSWORD@localhost:5432/farm_test pytest -q
```

Tests mock provider calls and exercise real PostgreSQL transactions and competing buyers.
