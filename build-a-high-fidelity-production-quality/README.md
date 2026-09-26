# PharmSync — FastAPI + MySQL Application (Steps 1–5)

This project contains the PharmSync homepage, MySQL-backed authentication and role access, inventory/POS/restocking, image-based medicine scanning, and the Step 5 Inventory Intelligence Agent. FastAPI is the only application backend. Browser storage contains only a JWT (never user records or passwords).

## Project structure

```text
pharmsync/
├── src/
│   ├── components/ (Navbar, InventoryIntelligence, scanner, shared homepage components)
│   ├── context/AuthContext.jsx
│   ├── pages/ (Home, Login, Register, Inventory, POS, Sales, Restock)
│   ├── services/api.js
│   ├── App.jsx
│   └── main.jsx
├── server/
│   ├── app/main.py
│   ├── app/routes/ (auth, inventory, sales, scanner, agent)
│   ├── app/services/ (OCR, intelligence calculations, daily agent)
│   ├── app/database/connection.py
│   ├── database/ (existing datasets/schema and migrations)
│   ├── tests/
│   ├── requirements.txt
│   ├── .env (local only; ignored by Git)
│   └── .env.example
├── .gitignore
└── README.md
```

## Database

Database name: `pharmsync`.

Apply the complete schema in `server/database/schema.sql`. Its `users` table uses `BIGINT UNSIGNED` primary IDs; unique email; an ENUM restricted to the three supported roles; bcrypt hash only; nullable license/registration values for the other role types; optional coordinates; verified/active flags; timestamps; and a nullable `node_id` index ready for a later organization-node relation.

```sql
CREATE DATABASE IF NOT EXISTS pharmsync
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE pharmsync;
CREATE TABLE IF NOT EXISTS users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  full_name VARCHAR(120) NOT NULL,
  email VARCHAR(254) NOT NULL UNIQUE,
  phone VARCHAR(32) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('retail_chemist','clinic_phc','charity_ngo') NOT NULL,
  organization_name VARCHAR(180) NOT NULL,
  license_number VARCHAR(100) NULL,
  registration_number VARCHAR(100) NULL,
  address VARCHAR(255) NOT NULL,
  city VARCHAR(100) NOT NULL,
  state VARCHAR(100) NOT NULL,
  latitude DECIMAL(10,7) NULL,
  longitude DECIMAL(10,7) NULL,
  node_id VARCHAR(32) NULL,
  verified BOOLEAN NOT NULL DEFAULT FALSE,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id), KEY idx_users_role_active (role, active), KEY idx_users_node_id (node_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

The canonical complete SQL (including named unique/index keys) is `server/database/schema.sql`. It can be applied from a MySQL client:

```powershell
mysql -u root -p -e "source server/database/schema.sql"
mysql -u root -p pharmsync -e "source server/database/seed.sql"
```

## Environment configuration

Edit `server/.env` locally before starting the API:

- Set `DB_PASSWORD` to the password for your MySQL account.
- Set `JWT_SECRET` to a high-entropy private random value (at least 32 random bytes); never commit it.
- `DB_HOST`, `DB_USER`, `DB_NAME`, `DB_PORT`, `PORT`, `CLIENT_ORIGIN` can be adjusted for your environment.
- `GEMINI_API_KEY` is required for Gemini image analysis; keep it private in this file. `GEMINI_MODEL` defaults to `gemini-3.8-flash`.
- Optional fallback: set `OCR_SPACE_API_KEY` to an OCR.Space API key (free tier available). If Gemini fails, this fallback extracts only explicitly labeled text; ambiguous fields remain blank for pharmacist review. The image is sent to OCR.Space only when this fallback is configured.
- `server/.env` is ignored by `.gitignore`; only `.env.example` is tracked.

The API exits with a clear message if required configuration is missing or MySQL cannot be reached. It prints “MySQL connected successfully” before listening when the DB is ready.

## Install and start

Prerequisites: Node.js (for the Vite frontend), Python 3.11+, and MySQL 8.0+. FastAPI is the only application backend.

From the repository root:

```powershell
npm install
cd server
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..
```

Create the database schema and demo users with the MySQL commands above. Then use two terminals:

```powershell
# Terminal 1 — from project root
cd server
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 5001
```

```powershell
# Terminal 2 — from project root
npm run dev
```

The API is at `http://localhost:5001`; the Vite app is at `http://localhost:5174`. The frontend defaults to `http://localhost:5001/api`; override with a root `.env` containing `VITE_API_URL` if needed.

## API endpoints

- `POST /api/auth/register` — validates fields and role, bcrypt hashes the password, inserts with parameterized SQL; returns a public user only.
- `POST /api/auth/login` — checks active status and bcrypt password, returns an 8-hour JWT and safe user fields.
- `GET /api/auth/me` — requires `Authorization: Bearer <token>`, returns the current safe user.
- `GET /api/health` — API health check.

## Frontend routes

- `/` — existing Step 1 homepage.
- `/login`, `/register` — real backend login and registration.
- `/inventory` — protected `retail_chemist` workspace.
- `/clinic` — protected `clinic_phc` workspace.
- `/charity` — protected `charity_ngo` workspace.
- `/transfers`, `/analytics` — protected Step 1 placeholders.

Role-incompatible users are redirected to their own dashboard. The portal navbar displays organization, role, profile details, and sign out after login.

## Demo accounts

All three seeded accounts use password `Demo@123`:

- `ramesh@pharmsync.demo` — Retail Chemist — Ramesh Medicals
- `priya@pharmsync.demo` — Clinic / PHC — Priya Community Clinic
- `charity@pharmsync.demo` — Charity / NGO — Helping Hands Free Clinic

`server/database/seed.sql` contains bcrypt hashes generated with 12 rounds using `bcryptjs` (bcrypt-compatible hashes). To generate a fresh hash for another seed, use Python bcrypt from the FastAPI environment and paste the resulting hash into SQL. No plaintext password is inserted into the users table.

## Verify account persistence

After applying the schema and starting MySQL + API, register from `/register`, then run:

```sql
USE pharmsync;
SELECT id, full_name, email, role, organization_name, active, verified, created_at
FROM users
WHERE email = 'you@organization.com';
```

Only `password_hash` is stored; the login API and `/me` response never return it. Login and page refresh call the running API; JWT expiration or invalidation clears the browser token and protected pages return to `/login`.

## Security scope

This is a development authentication foundation, not a production security certification. It includes bcrypt hashing, JWT expiry, environment-based secrets, parameterized SQL, role checks, input validation, CORS configuration, and generic server-side error responses. No password reset, email verification, organization verification workflow, rate limiting, or refresh-token rotation is included in this step.


## Step 3: Dataset-backed pharmacy inventory and POS

The Step 3 schema adds tables that preserve the supplied CSV identifiers and fields. It extends `users.node_id` as `VARCHAR(32)` and adds a foreign key to the single `pharmacy_nodes` table. Dataset rows are imported into MySQL once; React calls the FastAPI API and never reads CSV files.

### CSV to MySQL mapping and source data

The actual eight CSV files from the supplied ZIP are copied to `server/database/datasets/`. The full column map and the source-only field differences are documented in [server/database/CSV_MAPPING.md](C:\Users\HP\Documents\Codex\2026-09-25\build-a-high-fidelity-production-quality\server\database\CSV_MAPPING.md). The inventory table maps its displayed “Batch” to the real `batch_id` because the supplied CSV does not contain a separate `batch` column. The supplied source uses `unit_price_inr`, `manufacturing_date`, `transfer_manifests.csv`/`distance_km`, and `donations.csv`; those names are retained.

The current archive contains: 20 pharmacy nodes, 87 medicine batches, 600 sales, 34 clinic demand rows, 8 charity organizations, 36 transfer manifests, 60 donations, and 250 audit logs. Its charity file contains seven `EXT004`–`EXT010` node IDs missing from `pharmacy_nodes.csv`; import materializes them in that same canonical node table from the matching charity records, with unknown address/coordinates kept NULL. No rows are discarded.

### Additive database setup

If starting with an empty database, first run the Step 2 schema and seed, then the additive Step 3 schema. For a database that already has Step 2 users, run only the Step 3 schema migration before importing:

```powershell
# From project root, for a fresh database only
mysql -u root -p -e "source server/database/schema.sql"
mysql -u root -p pharmsync -e "source server/database/seed.sql"

# For fresh and existing databases; creates Step 3 tables and alters users.node_id
cd server
mysql -u root -p -e "source database/inventory_schema.sql"
```

Set `DB_PASSWORD` and a private `JWT_SECRET` in the ignored `server/.env` before starting the API. MySQL must be running. Never commit `server/.env`.

### Validate and import datasets

From the `server` directory:

```powershell
.\.venv\Scripts\python.exe database/import_datasets.py --dry-run
python database/import_datasets.py
```

Validation is read-only and checks exact headers, duplicate IDs, required values, numeric quantities/prices, date validity, node/batch links, and the pharmacy/clinic/charity roles referenced by the datasets. Invalid rows are reported with file and row number, and the import stops before writing. Import uses SHA-256 fingerprints and parameterized MySQL upserts inside a transaction. Re-importing the same CSV does not reapply it or reset quantities changed through POS. Changed source files are upserted; removed source rows are not deleted from the live database.

The importer reads the checked-in `server/database/datasets` directory.

### Step 3 API

All module endpoints require a JWT and the `retail_chemist` role. Every query scopes by the authenticated user’s linked `node_id`; the frontend cannot provide another pharmacy ID.

- `GET /api/inventory?search=` — node profile, live summary, FEFO-sorted batches; search executes in MySQL against name/medicine ID/batch ID/batch number.
- `GET /api/inventory?view=pos&search=` — sellable stock only, expiry ascending.
- `GET /api/inventory/batches/:batch_id`
- `POST /api/inventory/batches` — creates a server-generated `batch_id`; node ID is resolved from JWT.
- `PUT /api/inventory/batches/:batch_id` — edit or adjust; emits `INVENTORY_UPDATED` or `STOCK_ADJUSTED` audit event.
- `DELETE /api/inventory/batches/:batch_id` — refuses to delete batches with sales or transfer history.
- `GET /api/inventory/velocity?group_by=batch_id|medicine_id` — trailing 30-day quantity divided by 30.
- `GET /api/sales`, `GET /api/sales/summary`
- `POST /api/sales` with `{ "items": [{ "batch_id": "B0001", "quantity": 2 }] }` — locks each batch with `FOR UPDATE`, validates ownership/status/expiry/stock, calculates the amount from MySQL price, decreases quantity, inserts sale rows and audit logs, then commits as one transaction.

Clinic and charity accounts are blocked server-side from pharmacy inventory, POS and sales APIs. Existing clinic and charity Step 2 dashboards remain protected and available; their values remain clearly marked Step 2 placeholders.

### Frontend routes and package setup

Routes: `/inventory`, `/pos`, and `/sales` are protected retail-pharmacy pages; `/clinic` and `/charity` remain role-protected Step 2 pages. Root `/` and the Step 2 auth pages are preserved.

Install the frontend from the project root (`npm install`) and the FastAPI dependencies from `server` (`pip install -r requirements.txt`).

Run the FastAPI API from `server` and Vite from the project root in separate terminals. The frontend stays at `http://localhost:5174`; API stays at `http://localhost:5001`.

### Verify import and POS persistence

After the import, check actual database records:

```sql
SELECT COUNT(*) FROM pharmacy_nodes;
SELECT COUNT(*) FROM medicine_batches;
SELECT COUNT(*) FROM sales;
SELECT node_id, node_name, city, state FROM pharmacy_nodes WHERE node_type = 'Pharmacy';
```

Link each authenticated pharmacy user to its correct dataset node before opening inventory. Exact-name matches are linked automatically; no guessed node mapping is performed. The Ramesh Step 2 demo account does not exactly match the ZIP's generic pharmacy node names; choose its correct node and update `users.node_id` using the SQL in `CSV_MAPPING.md`.

After signing in as a linked retail chemist, open Inventory, search for a medicine, then POS. Add a batch to the cart and complete a sale. Verify the committed stock and sales values:

```sql
SELECT batch_id, node_id, quantity FROM medicine_batches WHERE batch_id = 'B0001';
SELECT sale_id, pharmacy_id, batch_id, quantity_sold, unit_price_inr, total_amount_inr
FROM sales ORDER BY created_at DESC LIMIT 10;
SELECT log_id, action, entity_type, entity_id, status
FROM audit_logs ORDER BY `timestamp` DESC LIMIT 10;
```

For a batch with quantity 40, a successful two-unit sale leaves quantity 38; the new sales row is tied to the same `batch_id`, uses its database unit price, and records its calculated total. Expiry labels are calculated from `expiry_date`; the importer and APIs do not automatically rewrite `batch_status` based on dates. POS excludes expired dates and inactive/expired statuses from saleable stock.


## Step 4 — FastAPI image scanner and stock receiving

The active backend is now Python FastAPI; the previous Express implementation and server-side npm manifests were removed. Step 1 homepage, JWT login/register, role routing, inventory, POS, and sales are still served by the same React frontend and the same MySQL database. Install Python 3.11 or newer, then from the project root run:

```powershell
cd server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python database/import_datasets.py --dry-run
```

Set DB credentials, JWT_SECRET, and GEMINI_API_KEY in `server/.env`. Apply the existing Step 2 and Step 3 schemas if needed, then apply the additive Step 4 migration:

```powershell
cd server
mysql -u root -p -e "source database/schema.sql"
mysql -u root -p -e "source database/inventory_schema.sql"
mysql -u root -p -e "source database/step4_migration.sql"
.\.venv\Scripts\python.exe database/import_datasets.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 5001
```

The image upload route accepts JPG/JPEG, PNG, and WEBP up to 8 MB as multipart form data at `POST /api/scanner/analyze-image`. Images are type- and signature-checked, sent to Gemini from the backend, and discarded after extraction. If Gemini fails and `OCR_SPACE_API_KEY` is configured, OCR.Space is tried as a fallback. API keys never reach React. BarcodeDetector is attempted in the browser for camera scans (DataMatrix when supported, common barcodes, and QR); a captured camera frame then enters the same image analysis, pharmacist review, and restock flow. If a device/browser cannot use its camera, the upload path remains available.

Both camera and upload converge on `POST /api/inventory/restock`. `GET /api/inventory/restock-check` checks the authenticated node, medicine ID, and batch number so the UI can ask before incrementing an existing batch. Restocking uses the existing `medicine_batches` table with its established `unit_price_inr` and `manufacturing_date` columns; Step 4 adds nullable `batch` and `storage_condition` columns and a unique key for (node_id, medicine_id, batch_number). No per-strip rows or image table are created. Successful restocks create an `INVENTORY_RESTOCKED` audit row. POS and inventory read the same batch row immediately.

FastAPI exposes the existing Step 2/3 routes as well: `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `GET/POST/PUT/DELETE /api/inventory...`, and `GET/POST /api/sales`. Each protected inventory/POS action verifies the JWT, active user, retail role, and server-resolved pharmacy node.

Start React in another PowerShell terminal from the project root with `npm run dev`; open `http://localhost:5174/`. The new restock page is `/inventory/restock` and is linked from Pharmacy Inventory. The API listens at `http://localhost:5001`. Run `python database/import_datasets.py --dry-run` to validate source rows without writing. Import requires the packages in `requirements.txt` and working MySQL credentials.

## Step 5 — Inventory Intelligence Agent

Step 5 extends the existing FastAPI + MySQL inventory, POS, and login implementation. It does not add tables or replace the imported PharmSync datasets. The agent calculates per-batch trailing 30-day sales velocity, stock coverage, projected expiry risk, discount pricing, and charity-fallback flags from live MySQL rows. The UI is integrated into `/inventory`; discounted batches remain visible in the existing POS at the computed offer price. Commercial sales are blocked at 30 days to expiry and expired batches remain unsellable.

### Database migration

`medicine_batches.batch_status` already supports the Step 5 statuses. Apply the additive indexes once (the script is safe to rerun):

```powershell
mysql -u root -p pharmsync -e "source server/database/step5_intelligence_migration.sql"
```

No new tables are created. The migration adds an index on `sales(pharmacy_id,sale_date,batch_id)` for the per-pharmacy velocity aggregation and an index on `medicine_batches(batch_status)`.

### Configuration

Add or update these values in `server/.env`:

```dotenv
RESTOCK_DAYS_THRESHOLD=15
INVENTORY_AGENT_HOUR=2
INVENTORY_AGENT_MINUTE=0
```

The daily scheduler uses Asia/Kolkata local time. Run one FastAPI worker when using the in-process APScheduler to avoid duplicate scheduled runs. The manual endpoint runs only for the authenticated retail chemist's linked pharmacy node.

### Start and verify

```powershell
cd server
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 5001
```

In another terminal:

```powershell
npm install
npm run dev
```

Open `http://localhost:5174/inventory`, sign in as a retail chemist, then use **Run analysis**. APIs (Axios uses the `/api` prefix):

- `GET /api/inventory/intelligence`
- `GET /api/inventory/intelligence/summary`
- `GET /api/inventory/alerts`
- `POST /api/agent/inventory/run`

The manual run response reports processed batches, restock/expiry alerts, discounts, charity-fallback batches, and expired batches. The intelligence GET endpoints are live calculations against the signed-in pharmacy's MySQL data; no browser-side inventory arrays are used.

### Tests

```powershell
cd server
python -m pytest tests/test_inventory_intelligence.py -q
```

The tests cover low-stock coverage, projected healthy stock, both discount tiers, the charity and expired thresholds, and zero-sales dead stock. Existing POS billing remains a MySQL transaction that locks the selected batch, checks stock, writes the sale, and decrements quantity; its server price now applies the same deterministic 30%/50% expiry discount. The UI displays that computed price. No fake sales are added by these tests.

## Step 7 — P2P redistribution

P2P suggestions are generated deterministically from verified `pharmacy_nodes`, eligible Step 5 batches, and open `clinic_demand` shortages. Matching uses exact medicine IDs plus normalized names, expiry-first allocation, shortage/stock caps, verified node checks, and Haversine distance when coordinates exist. It does not call Gemini. Pharmacies only see their own source opportunities, and clinics only see their own destination opportunities. A clinic account must have its real `users.node_id` linked to a verified clinic node before the demand screens can be used.

The additive/idempotent migration reuses `transfer_manifests` as the `transfer_receipt` store and adds `match_id`, `demand_id`, indexes, and the demand foreign key. Apply `server/database/step7_redistribution_migration.sql` once to an existing database before using these routes. Transfer approval is transactional: it locks the transfer, source batch, and shortage; revalidates eligibility; deducts source inventory; creates or increments the received destination batch; updates clinic demand; and writes the audit event together. Requests alone do not move stock.

New authenticated routes include `GET /api/transfers/opportunities`, `GET /api/transfers/opportunities/{match_id}`, `POST /api/transfers/opportunities/{match_id}/request`, `POST /api/transfers/opportunities/{match_id}/approve`, `GET /api/transfers/demand`, `GET /api/transfers/charity-fallback`, `GET /api/transfers/summary`, `GET /api/transfers/analytics`, `GET /api/transfers`, `GET /api/transfers/{transfer_id}`, `POST /api/transfers/{transfer_id}/approve`, `POST /api/transfers/{transfer_id}/reject`, and `PATCH /api/transfers/{transfer_id}/status`.

Open `/transfers` for the source/destination opportunity queue and `/analytics` for completed transfer summaries. Clinics also have `/clinic` for their imported shortage data. Run the backend from `server` with `python -m uvicorn app.main:app --reload --port 5001`; run the existing frontend with `npm run dev`. Run backend tests from `server` with `python -m pytest -q`.

Matching and calculation tests use isolated in-memory fixtures. The live matcher was also checked against imported MySQL data: it currently finds network-wide opportunities, but the signed-in Ramesh node N007 has no currently eligible matched demand. No real transfer was approved during verification, so existing pharmacy quantities and clinic stock were not changed.

## Patient medicine requests and pharmacy synchronization

The patient marketplace uses the existing `medicine_batches`, `sales`, and `pharmacy_nodes` data. Patient accounts use the existing JWT login with a new `patient` role. The additive migration `server/database/step6_patient_orders_migration.sql` adds that role, nullable patient organization details, `medicine_batches.reserved_quantity`, the single `medicine_orders` table, and a nullable unique `sales.order_id` link. Existing orders, users, inventory rows, and dataset columns are preserved. The completed pickup is recorded in the existing `sales` table so Step 5 sales velocity sees the transaction.

Set `MAX_USER_ORDER_QUANTITY=2` in `server/.env` to configure the per-order quantity cap. A pending request reserves stock on its existing batch row; the POS and P2P matcher use `quantity - reserved_quantity` as sellable/transferable stock. Cancellation releases the reservation. Completion reduces on-hand and reserved quantities together and inserts one linked sale in the same transaction.

Patient routes: `GET /api/medicines`, `GET /api/medicines/pharmacies`, `GET /api/medicines/{medicine_id}`, `GET /api/medicines/{medicine_id}/alternatives`, `POST /api/orders`, `GET /api/orders/my`, `GET /api/orders/{order_id}`, and `POST /api/orders/{order_id}/cancel`. Pharmacy routes: `GET /api/pharmacy/orders` and `PATCH /api/pharmacy/orders/{order_id}/status`. Patient accounts see `/medicines` and `/my-orders`; retail chemists see `/pharmacy/orders`. Marketplace results, pharmacy order notifications, and both order histories come from FastAPI/MySQL. Pharmacy order notifications refresh every 20 seconds.

After applying the migration, restart FastAPI and Vite. Register a Patient / User account, sign in, search a medicine such as Amlodipine, and request up to the displayed maximum. Sign in as a retail chemist linked to that offer's pharmacy node; open Medicine requests, confirm the request, mark it Ready for pickup, then complete pickup. Patient order status should follow each change. To check stock, inspect the existing batch row: pending/confirmed/ready quantities are in `reserved_quantity`; completed orders reduce `quantity` and `reserved_quantity` once and add one `sales` row with the matching `order_id`.

The implementation was verified with 15 automated tests and live MySQL API workflows for max-quantity rejection, patient request, pharmacy visibility, confirmation, cancellation/release, ready-for-pickup, completion, synchronized patient status, linked sales insertion, and restoration of test stock after verification.

## Step 8 — AI Network Intelligence, Analytics & Explainable Insights

Step 8 extends the existing FastAPI service and `/analytics` route. It reads the existing MySQL tables (`medicine_batches`, `sales`, `pharmacy_nodes`, `clinic_demand`, `transfer_manifests`, `medicine_orders`, `charity_organizations`, and `donations`) and does not create a separate analytics database or invented metrics. Inventory and expiry charts are current snapshots because the application does not store historical inventory snapshots. Sales, orders, transfers, and donations use the selected date range where their source tables have event dates.

### Access and scope

- Retail chemists see their own batches, sales, orders, restock/expiry data, and P2P opportunities. Network shape and shortages are aggregate counts; patient identity is not included.
- Clinics see verified network supply/expiry summaries, their own demand/transfers, and relevant P2P suggestions. They do not receive pharmacy sales or patient identities.
- Charity accounts can open `/analytics` to see current near-expiry fallback supply summaries and donation records for their linked node. They do not see pharmacy sales or patient orders.
- No admin role was added. The API derives role and `node_id` from the authenticated JWT user record.

### New endpoints

All endpoints require a valid JWT. Supported period query values are `7d`, `30d`, `90d`, or `custom` with `start=YYYY-MM-DD&end=YYYY-MM-DD` (maximum 366 days).

- `GET /api/analytics/dashboard?period=30d` — one aggregate dashboard payload used by the React page.
- `GET /api/analytics/summary`
- `GET /api/analytics/inventory-health`
- `GET /api/analytics/velocity`
- `GET /api/analytics/restock`
- `GET /api/analytics/expiry-risk`
- `GET /api/analytics/discounts`
- `GET /api/analytics/redistribution`
- `GET /api/analytics/orders`
- `GET /api/analytics/network`
- `GET /api/analytics/impact`
- `GET /api/analytics/insights`
- `POST /api/analytics/query` with `{ "question": "Which medicines are at expiry risk?" }` — maps text to a fixed supported intent and selects already-computed backend results. It cannot create or execute SQL.

The inventory-health and discount stages use the Step 5 deterministic `evaluate_batch` logic and 30-day sales aggregation. Available stock subtracts patient reservations. Velocity thresholds are centralized in environment configuration; defaults are `VELOCITY_FAST_UNITS_PER_DAY=1.0` and `VELOCITY_SLOW_UNITS_PER_DAY=0.1`. The existing `RESTOCK_DAYS_THRESHOLD=15` is reused. Suggested redistribution opportunities are calculated by the Step 7 matcher and remain separate from received/completed transfer records. Impact labels explicitly distinguish expiry risk, discount eligibility, actual completed transfers, completed discounted patient orders, charity fallback, and completed donations.

### AI provider and deterministic fallback

AI is an optional explanation layer only. The API passes structured MySQL-derived metrics to the selected provider; it cannot write data or decide stock, prices, discounts, order authorization, or transfer eligibility. If there is no key, the provider call fails, or the response is invalid, backend-generated explainable insights remain available and the dashboard displays the deterministic fallback state.

Add these optional settings in `server/.env`:

```dotenv
AI_PROVIDER=none
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.8-flash
HUGGINGFACE_API_KEY=
HUGGINGFACE_MODEL=mistralai/Mistral-7B-Instruct-v0.3
VELOCITY_FAST_UNITS_PER_DAY=1.0
VELOCITY_SLOW_UNITS_PER_DAY=0.1
```

Use `AI_PROVIDER=gemini` with `GEMINI_API_KEY`, `AI_PROVIDER=huggingface` with `HUGGINGFACE_API_KEY`, or `AI_PROVIDER=none`. No key is needed for analytics or Ask PharmSync's controlled keyword intent mode. Keep provider keys only in ignored `server/.env`; no frontend key or new package is needed.

### Run and verify

From the project root, start FastAPI in one terminal and React in another:

```powershell
cd server
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 5001
```

```powershell
npm run dev
```

Sign in with a linked retail chemist, clinic, or charity account and open `http://localhost:5174/analytics`. Choose a period, refresh after a sale/order/transfer, and ask a question from the suggested prompts. For example, with a retail JWT:

```powershell
Invoke-RestMethod "http://localhost:5001/api/analytics/dashboard?period=30d" -Headers @{ Authorization = "Bearer YOUR_JWT" }
```

No schema migration was needed, no packages were added, and analytics is read-only. The backend tests include controlled intent mapping (including a SQL-injection-shaped question), time-range validation, deterministic insight grounding, and AI fallback. Verification completed with 19 passing tests, Python compile checks, a successful Vite production build, and a live MySQL-backed dashboard/query request for the linked N007 retail account.
