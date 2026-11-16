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
pip install -r requirements.lock
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

## Reproduce the complete flow

With API and database running, create an administrator as above, then run:

```sh
python scripts/demo.py
python -m app.worker --once
```

The script prompts for admin credentials and new buyer/rider credentials, creates stock, registers
and logs in the buyer, browses products, places and retries an order, confirms/prepares it using the
admin's business authority, assigns a rider, dispatches/delivers, records cash, and checks completion.
Use fresh buyer/rider phone numbers per run. It changes your local database. Do not use on production.
The seller can perform confirmation/preparation using their own login; the tests exercise this path.

## Farm records

Create broiler/layer batches using `/flocks`. One immutable daily record per flock/date contains
mortality, eggs (layers only), and feed kilograms. Repeating identical daily data returns the original;
conflicting data returns 409. Mortality updates biological counts; recording eggs does not create stock.

`POST /flocks/{id}/transfers` explicitly creates saleable inventory. Egg transfers name a daily record;
a tray is **30 eggs**. Bird harvests specify `birds_removed`; kilogram harvests also specify measured
saleable weight. Transfers share the flock's business, carry an immutable source key, and emit inventory
movements. Identical source retries return the existing transfer; conflicting retries fail. Manual stock
receipts are for purchased/opening stock; use production transfers for flock output to preserve lineage.
Cancellation of an order never adds birds back into a flock.

Admin assigns seller/staff business membership at `/businesses/{id}/members`. Owners and assigned
staff can manage that business; other businesses stay private. Expenses have unique source references,
optional flock attribution, date, category and KES amount. `/businesses/{id}/summary?start=YYYY-MM-DD&end=YYYY-MM-DD`
reports mortality, eggs, feed, sales by unit, cash receipts and expenses over Nairobi calendar dates.
Cash less expenses is not accrual profit; no invented feed/egg/bird unit conversions are applied.

## Scope and remaining work

Implemented: ordering milestone plus basic production/expense milestone. No React frontend, AI,
M-Pesa, refunds, partial cash payments, rider reassignment, record correction workflow, live handset
receipt tracking, multi-seller carts or accounting valuation. Configure HTTPS, edge login rate limits,
backups and operational monitoring before public deployment. The local Compose database is bound to
loopback; its password must be supplied. Tokens expire after 8 hours; there is no refresh/revocation UI.

Money and quantity fields are returned as decimal strings to avoid JSON floating point rounding.
Runtime dependencies are pinned in `requirements.lock`; regenerate with
`uv pip compile pyproject.toml -o requirements.lock` when updating dependencies.
If host ports are occupied, set `API_PORT` / `POSTGRES_PORT` in `.env` and match the host
`DATABASE_URL`. If the local Compose build plugin crashes, use `COMPOSE_BAKE=false docker compose up --build -d`.

Development verification created local demo records. If `DEMO_ADMIN_PHONE` and
`DEMO_ADMIN_PASSWORD` exist in your ignored `.env`, they are the generated local demo login.
They are not part of app configuration and are never shipped in Git or the container image.
