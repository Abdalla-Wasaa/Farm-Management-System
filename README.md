# Kuku Farm · Poultry farm & marketplace

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
Cash uses `app.services.record_payment`. Sandbox M-Pesa uses a separate durable STK request
and authenticated status-query verification boundary in `app.payments`; see the Daraja section below.

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

Implemented: connected React frontend, ordering and basic production/expense milestones. No AI,
live M-Pesa, refunds, partial cash payments, rider reassignment, record correction workflow, live handset
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


## Daraja M-Pesa sandbox

The server only contacts `https://sandbox.safaricom.co.ke`; live mode is not accepted.
Keep `DARAJA_CONSUMER_KEY`, `DARAJA_CONSUMER_SECRET` and `DARAJA_PASSKEY` in the ignored
`.env`. Set `DARAJA_MODE=sandbox`, `DARAJA_SHORTCODE=174379`, and a full public HTTPS
`DARAJA_CALLBACK_URL`. `.env.example` has blank credentials and disabled mode.
SMS remains independently configured; keep `SMS_MODE=dry-run` during testing.

Local mocked tests need no tunnel, Safaricom connection or real phone interaction. For an actual
sandbox callback, install/authenticate ngrok using https://ngrok.com/docs/start, then run:

```sh
ngrok http 8001
# Copy the generated HTTPS URL into .env, adding /payments/mpesa/callback:
# DARAJA_CALLBACK_URL=https://YOUR_ASSIGNED_DOMAIN/payments/mpesa/callback
docker compose up -d --force-recreate api worker
```

Use the API's actual host port (`API_PORT`, default 8000, currently 8001 in this workspace).
Do not expose a development server containing real customer data. If the tunnel URL changes,
update `.env` and recreate the API/worker. No callback URL is invented or hardcoded.

After a pickup/delivery order is **completed and unpaid**, the buyer can request payment:

```http
POST /orders/ORDER_ID/payments/mpesa
Authorization: Bearer BUYER_TOKEN
Idempotency-Key: unique-payment-request-key
Content-Type: application/json

{"phone":"YOUR_SANDBOX_TEST_PHONE"}
```

Use a phone number you control or a provider-approved test number. The server takes the exact total
from the order; STK requires a whole KES amount, so fractional totals are rejected, never rounded.
This increment supports payment at handover, not advance payment. The response is HTTP 202 with
an intent ID and `environment: sandbox`. The existing worker submits the request and polls its
status. `GET /orders/ORDER_ID/payments/mpesa` shows progress to authorized order viewers.

Public callbacks are **untrusted hints** and never create a receipt or send a success SMS.
Only an authenticated STK query matching both stored checkout and merchant request identifiers
can create one `mpesa_sandbox` payment and enqueue one explicitly labelled sandbox SMS.
Polling handles missing callbacks too. Query receipts use `STK:<CheckoutRequestID>` as an internal
verified reference; the query does not supply a verified M-Pesa receipt number, so the application
does not invent one or trust an unsigned callback's receipt. Sandbox success changes payment status
for simulation only and never represents real money. Cash summaries exclude sandbox receipts.

Identical payment keys replay the same intent. Only one active intent is allowed per order;
cash collection is blocked while a request is unresolved. A confirmed failed attempt allows a new
key. Transport ambiguity or a worker crash during submission becomes `uncertain` instead of
repeating a potentially accepted STK prompt. Unresolved status queries back off, up to 20 checks,
then require investigation. Automated reconciliation of ambiguous submissions, manual resolution,
refunds, prepayment, real receipt reconciliation, and live onboarding are not implemented.

Protocol reference: https://github.com/safaricom/mpesa-php-sdk/blob/master/src/Mpesa.php

## React frontend

The responsive React/TypeScript app lives in `frontend/`. It uses Vite, Tailwind CSS,
React Router, TanStack Query, React Hook Form and Zod. All application data comes from
FastAPI; no sample records are embedded in the UI.

Development (Node 22+):

```sh
cd frontend
npm ci
cp .env.example .env.local
# VITE_API_BASE_URL=http://localhost:8001
npm run dev
```

Open http://localhost:5173. The existing API runs on http://localhost:8001; CORS explicitly
allows `http://localhost:5173` and `http://127.0.0.1:5173`. Add a different local origin to
backend `CORS_ORIGINS` if you change the frontend port, then restart the API. Only
`VITE_API_BASE_URL` belongs in frontend environment files. Never put provider keys, JWT
signing keys or account passwords in a `VITE_` variable: these are public build values.

`npm run build` runs TypeScript checks and creates `frontend/dist/`; `npm run preview`
serves that build locally. BrowserRouter hosting must serve `index.html` for application
routes. The provided nginx configuration handles this in Docker.

For the complete persistent local stack (requires Docker Hub access):

```sh
docker compose --profile frontend up --build -d
```

The frontend is served on port 5173 (`FRONTEND_PORT`), with the API URL compiled from
`FRONTEND_API_URL` (default `http://localhost:8001`). Set it to match your API host port.
Changing the API URL requires rebuilding the frontend image. Keep CORS aligned with the
frontend origin. This is local hosting; no public deployment is configured.

Authentication uses the existing Bearer JWT. The browser stores it in per-tab
`sessionStorage`, not a compiled credential or URL. Logout clears the token and cached
private data. Expired tokens return the user to sign-in. Routes and navigation follow
roles, and the API independently enforces permissions. There is no password-reset,
refresh-token or account-phone editing endpoint, so the UI does not pretend to offer them.

### Role-by-role walkthrough

1. **Administrator:** use the existing hidden-password `create-admin` command. Log in at
   `/login`. Under **People & SMS**, create seller/staff/rider accounts and grant seller or
   staff access to the selected farm. Share generated passwords outside Git. The bootstrap
   administrator's farm already exists; no privileged self-registration is available.
2. **Seller/staff:** choose the active farm, open **Produce & inventory**, create eggs,
   broilers, dressed chicken or spent layers, and add purchased/opening stock. Use unique
   receipt references. Product names, descriptions and prices can be edited. Units/categories are fixed once inventory movements exist. Signed stock
   adjustments cannot remove reserved stock. Farm output should use production transfers.
3. **Buyer:** register with a Kenyan mobile number and password, browse **Marketplace**,
   open a product and add a selling quantity. A basket accepts only one seller. Choose
   pickup or delivery, enter the delivery address, and review KES totals. Order updates use
   the buyer's registered phone; checkout does not submit an unsupported contact-number field.
4. **Buyer checkout:** place the order once. Buttons disable during submission. If the
   response is lost, use **Recover saved submission** or inspect order history. Recovery
   reuses the saved body and idempotency key, even when the original order already reserved
   the available stock. It does not create a fresh request. Cancellation requires confirmation.
5. **Seller:** under **Orders**, confirm → prepare → ready. For pickup, confirm actual
   collection using **Complete pickup**. Existing order-item descriptions and prices stay fixed.
6. **Administrator:** assign a rider to a confirmed/preparing/ready delivery order.
7. **Rider:** **My deliveries** shows assigned jobs. Open the order to see the farm contact,
   buyer phone and delivery address. The backend has no exact pickup-location field, so the
   UI explicitly asks the rider/buyer to coordinate that point with the farm contact. Confirm
   pickup/dispatch, then confirm delivery. Other riders cannot change this order.
8. **Cash:** after completion, the authorized seller/admin or assigned delivery rider can
   record physically received cash using a unique receipt reference. The buyer then sees
   the completed order, delivered status and paid status. Active/unresolved M-Pesa intents
   block cash recording to prevent a second collection.
9. **M-Pesa sandbox:** the action is shown only for a completed unpaid order when the server
   reports sandbox callback configuration ready. An accepted request stays unpaid until the
   worker independently verifies it. UI polling stops after two minutes and on navigation;
   **Refresh status** checks again without creating another prompt. A confirmed cancellation
   or failure permits a new request; an uncertain outcome requires administrator investigation.
   Sandbox payments are labelled simulations. No live mode is supported.
10. **Farm staff:** create a broiler/layer batch, then record daily mortality, eggs and feed.
    Recording production does not add marketplace stock. Under **Transfer to inventory**,
    select a product, production record for eggs (30 eggs per tray), or birds removed for
    harvest. Reuse a source reference after failure. Then verify inventory balances/movements.
    Add dated expenses and use **Reports** for the real production/sales/cash summaries.

Admin SMS screens show only notification states supported by the backend. `dry-run` means
no SMS was sent; `accepted` means submitted to the provider, not delivered to a handset.
Africa's Talking stays in dry-run during development.

### Browser tests and generated local accounts

Playwright uses a dedicated PostgreSQL database, a separate FastAPI process on port 8012,
and Vite on port 5174. It never resets your regular farm database. The seed script refuses
any database whose name does not end `_e2e_test`, but **does truncate that dedicated test
DB at the start of each run**. Do not point it at valuable data.

```sh
# On the local PostgreSQL container used for tests in this workspace:
docker exec farm-dev-postgres createdb -U farm farm_frontend_e2e_test
# Or create an equivalent dedicated database with your PostgreSQL tools.
cd frontend
npm ci
npx playwright install chromium
E2E_DATABASE_URL=postgresql+psycopg://farm:YOUR_PASSWORD@localhost:5432/farm_frontend_e2e_test npm run test:e2e
```

Omit `E2E_DATABASE_URL` only when the default local `farm:farm` test credentials apply.
Ports 8012 and 5174 must be free; test servers are never reused silently. Backend pytest
continues to use its separate `_test` database as described above.

Each run generates account passwords into the ignored, mode-0600
`.local/e2e-accounts.json`. No passwords are committed. For manual isolated testing, launch
`scripts/e2e_server.py` with the same test database URL and point Vite's API base URL at
`http://127.0.0.1:8012` (serve Vite on port 5174). The server seeds all privileged accounts
and an alternate buyer; the primary buyer is registered by the browser test. No worker is
started, and fake Daraja configuration is used only in this isolated process.

Tests cover registration/login, catalogue/stock setup, checkout, seller preparation, rider
assignment, dispatch/delivery, cash receipt, final buyer status, role/session restrictions,
production transfer, expenses/reports, and lost-response idempotency/cancellation. Payment
UI tests use the real API and payment services with **fake provider functions**, not real
STK prompts. They cover pending, success, payer cancellation, retry and uncertain timeout.
They are not evidence of real callback connectivity. Traces/screenshots are ignored local
artifacts and can contain generated test account details.

For an actual manual Daraja test, separately configure the public HTTPS callback as described
above, use a number you control, complete an unpaid order, and explicitly request a sandbox
payment. Do not run this step unattended. No real STK request or live SMS is sent by the
frontend build, backend tests, browser tests, or account seed scripts.

Local verification passed 42 backend tests and 7 Playwright scenarios. The frontend production
build also passed TypeScript checking and was checked for configured backend/provider secrets.
The frontend Docker image also built successfully after a transient Docker Hub DNS issue
cleared. The nginx frontend now serves port 5173, including direct links to application routes.
Existing backend containers continue running on port 8001.
