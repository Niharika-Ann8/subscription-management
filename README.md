# Subscription Management System

Odoo x Make-A-Ton hackathon project. One platform to run plans, subscriptions, recurring billing, payments and finance reporting for a subscription business (Brightloop Software).

**Stack:** Python, Streamlit, SQLite

## Features

- **Auth and roles:** signup with password rules (9+ characters, uppercase, lowercase, special character), unique email, password reset. Roles: Admin, Staff, Customer. Only Admin can add Staff.
- **Catalog:** products with cost and sales price, variants (e.g. Odoo brand adds +560), plans (Daily, Weekly, Monthly, Yearly) with min quantity and dates.
- **Subscriptions:** lifecycle Draft, Quotation, Confirmed, Active, Closed, with product lines and taxes.
- **Billing:** one-click billing run creates invoices from due Active subscriptions. Taxes and discounts are applied automatically, and nothing is billed twice.
- **Discounts:** Admin-only rules (fixed or percentage, min quantity or amount, dates, usage limit).
- **Payments:** UPI, Card or Bank Transfer, recorded against invoices. Invoice flow: Draft, Confirmed, Paid.
- **Finance dashboard:** active subscriptions, revenue, outstanding amount, overdue invoices, with filters and summaries.
- **Customer portal:** customers see only their own subscriptions and invoices.

## Run it

```bash
git clone https://github.com/Niharika-Ann8/subscription-management.git
cd subscription-management
pip install -r requirements.txt
python seed.py
streamlit run app.py
```

`python seed.py` loads demo data (about 215 rows) and can be re-run at any time. It wipes and reseeds the local database.

## Demo logins

| Role | Email | Password |
|---|---|---|
| Admin | admin@brightloop.com | Admin@12345 |
| Staff | staff1@brightloop.com | Staff@12345 |
| Customer | customer1@mail.com (up to customer12) | Customer@123 |

## Project structure

```
db.py        SQLite schema and helper functions
seed.py      demo data seeder
auth.py      login, signup, password reset, staff management
catalog.py   products, variants, plans, subscription lifecycle
billing.py   discounts, billing run, invoices, payments
app.py       main app: login gate, sidebar, finance dashboard
```

## Team

- @Niharika-Ann8: database, seed data, main app and dashboard
- @rizaismailsky-droid: auth and catalog
- @nandanavr005-ops: billing and payments