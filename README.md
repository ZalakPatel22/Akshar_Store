# AKSHAR STORE

A first working foundation for Akshar Store: a public React storefront, secure owner-only administration, SQLite-backed products/orders, stock movements, payments, order tracking and printable PDF invoices. This repository was empty when inspected, so this commit establishes the project rather than replacing existing code. This is an incremental foundation—not yet the complete business-management scope in the original specification.

## Implementation plan
1. Establish Flask/SQLite and React/Vite, configuration, migrations and secure initial owner setup.
2. Implement core product/catalog management, online checkout, stock deduction/restoration, order/payment tracking and the mandated invoice identity.
3. Add variants/images/barcodes, offline POS, full customer/expense management, analytics/exports, WhatsApp templates, and complete responsive admin modules.
4. Add broad integration/security/frontend tests, run them, address gaps and document deployment/backups.

This commit implements the initial foundation and a subset of steps 1–2. Do not treat the later phases as complete.

## Included now
- Storefront loads active products and categories from SQLite; search and cart are functional.
- Guest checkout creates a real order and customer, deducts stock and records inventory movement in a database transaction. COD is clearly stated; no payment gateway is claimed.
- Admin login uses Werkzeug password hashes, secure HTTP-only session cookies, CSRF header validation, restricted CORS, and login/order rate limits. Public admin registration is intentionally absent.
- Admin can create/list/edit/archive products and create categories; browse orders, record payments, update order status and download invoices.
- Cancellation restores stock once; order item name/SKU/price are stored as historical snapshots.
- Public order tracking requires both order number and matching mobile number and returns only status and item names/quantities.
- PDF invoice prominently prints **AKSHAR STORE**, exactly `Contact: 9979494032, 8866912212`, a thin divider and the required thank-you line.
- SQLite foreign keys enabled, Decimal/Numeric currency fields, Flask-Migrate, and non-destructive `init-db` command.

## Not implemented yet
Variants and independent variant stock, product image uploads, offline/manual POS, full customer/expense modules, analytics, Excel/CSV/PDF report exports, saved sequential invoice records, barcode/QR labels, WhatsApp message tooling, full admin CRUD screens, and comprehensive test coverage remain planned. Invoice PDFs are generated on demand. Product UI and order UI are intentionally MVP-level.

## Stack and ports
- API: Flask at `http://127.0.0.1:5000`
- UI: Vite at `http://127.0.0.1:5173`
- Database: SQLite at `backend/instance/akshar_store.db` by default
- React 18, Vite 6, Flask 3, SQLAlchemy 2, Flask-Migrate, ReportLab

## Setup (Windows PowerShell)
Open a terminal in the repository root.

```powershell
Copy-Item .env.example .env
# Edit .env and set SECRET_KEY and unique admin credentials before starting.
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SECRET_KEY = "use-a-long-random-value-here"
$env:AKSHAR_ADMIN_USERNAME = "owner"
$env:AKSHAR_ADMIN_PASSWORD = "use-a-unique-password-at-least-12-chars"
flask --app app init-db
flask --app app create-admin
python run.py
```

In another PowerShell terminal from repository root:

```powershell
cd frontend
npm install
npm run dev
```

`python-dotenv` loads `.env` automatically when installed. Set the same secret/admin variables in the backend process environment or `.env`; never commit `.env`. For a remotely deployed site, set `COOKIE_SECURE=true` and serve over HTTPS. Configure `FRONTEND_ORIGIN` to the exact trusted UI origin.

## Migrations
The `init-db` command creates missing tables without resetting the database. For schema evolution, use Flask-Migrate:

```powershell
flask --app app db init
flask --app app db migrate -m "describe schema change"
flask --app app db upgrade
```

Review generated migrations before applying them. Do not delete the live SQLite database to resolve migration problems.

## Verify / tests
- Visit `/` and check that the store loads (empty catalog until products are entered).
- Visit `/admin/login`, sign in with the first-admin credentials, then use the API to create product/category records. The current admin UI is a read-oriented dashboard; product CRUD is available through the protected REST API.
- Add an in-stock product through `POST /api/admin/products`, then use storefront checkout. Check `/api/admin/orders`, stock, and downloadable invoice.
- Track with `GET /api/orders/track?order_number=...&phone=...`.
- Backend: `cd backend; pytest` (tests are a starting smoke suite, not a complete acceptance suite).
- Frontend build: `cd frontend; npm install; npm run build`.

Admin write API requests require the session cookie and `X-CSRF-Token` returned by login (or `GET /api/auth/csrf`). Example routes are listed in `backend/app.py`.

## Back up and restore SQLite
Stop the backend before copying the file, or use SQLite's online backup API for a running production database. Basic stopped-service copy:

```powershell
Copy-Item backend\instance\akshar_store.db .\akshar_store-backup.db
Copy-Item .\akshar_store-backup.db backend\instance\akshar_store.db
```
Keep backups encrypted and outside the public web root. Test restores periodically.

## Important operational limits
This is not yet a complete production-ready business platform: configure HTTPS, strong secrets, backups, monitoring and a production WSGI server before launch. The current catalog has simple product-level stock (not variants). Checkout reserves stock immediately. Confirming third-party payment is not supported. Validate the remaining phase checklist and add workflow/security tests before using for live commerce.
