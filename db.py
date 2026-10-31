
"""db.py - SQLite schema + helpers. Teammates: import from here, never write raw connections."""
import sqlite3, hashlib, os, secrets
from datetime import date

DB_PATH = "database.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,                -- hashed, use hash_password()
    role TEXT NOT NULL DEFAULT 'Customer'  -- 'Admin' | 'Staff' | 'Customer'
);
CREATE TABLE IF NOT EXISTS password_resets (
    token TEXT PRIMARY KEY, email TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, type TEXT, base_price REAL NOT NULL,
    cost_price REAL DEFAULT 0, notes TEXT
);
CREATE TABLE IF NOT EXISTS product_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    attribute TEXT NOT NULL,               -- e.g. 'Brand'
    value TEXT NOT NULL,                   -- e.g. 'Odoo'
    extra_price REAL DEFAULT 0             -- e.g. 560
);
CREATE TABLE IF NOT EXISTS taxes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, rate REAL NOT NULL -- percent, e.g. 18
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, price REAL NOT NULL,
    billing_period TEXT NOT NULL,          -- 'Daily'|'Weekly'|'Monthly'|'Yearly'
    min_qty INTEGER DEFAULT 1,
    start_date TEXT, end_date TEXT,
    auto_close INTEGER DEFAULT 0, allow_pause INTEGER DEFAULT 1,
    allow_renew INTEGER DEFAULT 1, allow_early_close INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS quotation_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, plan_id INTEGER REFERENCES plans(id),
    validity_days INTEGER DEFAULT 30
);
CREATE TABLE IF NOT EXISTS quotation_template_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER NOT NULL REFERENCES quotation_templates(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    variant_id INTEGER, qty INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT UNIQUE,                    -- e.g. 'SUB-0001'
    customer_email TEXT NOT NULL,
    plan_id INTEGER REFERENCES plans(id),
    status TEXT DEFAULT 'Draft',           -- Draft|Quotation|Confirmed|Active|Closed
    start_date TEXT, expiry_date TEXT, payment_terms TEXT,
    total_amount REAL DEFAULT 0,
    next_billing_date TEXT                 -- billing run uses this to avoid double billing
);
CREATE TABLE IF NOT EXISTS subscription_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL REFERENCES subscriptions(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    variant_id INTEGER, qty INTEGER DEFAULT 1,
    unit_price REAL NOT NULL, tax_id INTEGER REFERENCES taxes(id),
    amount REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS discounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    type TEXT NOT NULL,                    -- 'Percentage' | 'Fixed'
    value REAL NOT NULL,
    min_qty INTEGER DEFAULT 1, min_amount REAL DEFAULT 0,
    start_date TEXT, end_date TEXT,
    usage_limit INTEGER, times_used INTEGER DEFAULT 0,
    product_id INTEGER REFERENCES products(id),  -- NULL = whole subscription
    active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER REFERENCES subscriptions(id),
    customer_email TEXT NOT NULL,
    base_amount REAL NOT NULL, tax_amount REAL NOT NULL,
    discount_amount REAL DEFAULT 0, total_amount REAL NOT NULL,
    status TEXT DEFAULT 'Draft',           -- Draft|Confirmed|Paid (+Cancelled)
    due_date TEXT,
    period_start TEXT,
    UNIQUE(subscription_id, period_start)  -- DB-level guard: never bill twice
);
CREATE TABLE IF NOT EXISTS invoice_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    product_id INTEGER, description TEXT, qty INTEGER,
    unit_price REAL, tax_amount REAL, amount REAL
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER REFERENCES invoices(id),
    method TEXT NOT NULL,                  -- 'UPI'|'Card'|'Bank Transfer'
    amount REAL NOT NULL, payment_date TEXT, note TEXT
);
CREATE INDEX IF NOT EXISTS idx_sub_status ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_sub_cust ON subscriptions(customer_email);
CREATE INDEX IF NOT EXISTS idx_inv_status ON invoices(status, due_date);
CREATE INDEX IF NOT EXISTS idx_inv_cust ON invoices(customer_email);
CREATE INDEX IF NOT EXISTS idx_pay_inv ON payments(invoice_id);
"""

TABLES = {"users", "password_resets", "products", "product_variants", "taxes", "plans",
          "quotation_templates", "quotation_template_lines", "subscriptions",
          "subscription_lines", "discounts", "invoices", "invoice_lines", "payments"}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_conn() as c:
        c.executescript(SCHEMA)


# ---------- generic helpers ----------
def query(sql, params=()):
    """Run SELECT -> list[dict]."""
    with get_conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def query_one(sql, params=()):
    """Run SELECT -> dict or None."""
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=()):
    """Run INSERT/UPDATE/DELETE -> lastrowid."""
    with get_conn() as c:
        return c.execute(sql, params).lastrowid


def insert(table, data: dict):
    """insert('products', {'name':'X','base_price':100}) -> new id"""
    assert table in TABLES, f"unknown table {table}"
    cols = ",".join(data)
    qs = ",".join("?" * len(data))
    return execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", tuple(data.values()))


def update(table, row_id, data: dict):
    """update('invoices', 5, {'status':'Paid'}) -> None"""
    assert table in TABLES, f"unknown table {table}"
    sets = ",".join(f"{k}=?" for k in data)
    execute(f"UPDATE {table} SET {sets} WHERE id=?", (*data.values(), row_id))


def get_by_id(table, row_id):
    """-> dict or None"""
    assert table in TABLES
    return query_one(f"SELECT * FROM {table} WHERE id=?", (row_id,))


def list_all(table, **filters):
    """list_all('subscriptions', status='Active') -> list[dict]"""
    assert table in TABLES
    if not filters:
        return query(f"SELECT * FROM {table}")
    where = " AND ".join(f"{k}=?" for k in filters)
    return query(f"SELECT * FROM {table} WHERE {where}", tuple(filters.values()))


# ---------- auth helpers (Member 1) ----------
def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 100_000)
    return salt.hex() + "$" + h.hex()


def verify_password(pw: str, stored: str) -> bool:
    salt, h = stored.split("$")
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 100_000).hex() == h


def create_user(email, password, role="Customer"):
    """-> new id, or None if email already exists."""
    if get_user(email):
        return None
    return insert("users", {"email": email.lower().strip(),
                            "password": hash_password(password), "role": role})


def get_user(email):
    """-> dict(id,email,password,role) or None"""
    return query_one("SELECT * FROM users WHERE email=?", (email.lower().strip(),))


def login(email, password):
    """-> user dict if valid, else None"""
    u = get_user(email)
    return u if u and verify_password(password, u["password"]) else None


def create_reset_token(email, expires_at):
    """-> token string (email it / show it in demo)"""
    t = secrets.token_urlsafe(16)
    insert("password_resets", {"token": t, "email": email, "expires_at": expires_at})
    return t


# ---------- catalog / subscription helpers ----------
def get_variants(product_id):
    """-> list[dict] variants of a product"""
    return query("SELECT * FROM product_variants WHERE product_id=?", (product_id,))


def get_subscription_lines(sub_id):
    """-> list[dict] lines joined with product name and tax rate"""
    return query("""SELECT l.*, p.name AS product_name, COALESCE(t.rate,0) AS tax_rate
                    FROM subscription_lines l
                    JOIN products p ON p.id=l.product_id
                    LEFT JOIN taxes t ON t.id=l.tax_id
                    WHERE l.subscription_id=?""", (sub_id,))


def next_sub_number():
    """-> 'SUB-0001' style number"""
    n = query_one("SELECT COUNT(*) AS n FROM subscriptions")["n"] + 1
    return f"SUB-{n:04d}"


# ---------- billing helpers (Member 2) ----------
def get_due_subscriptions(today=None):
    """-> Active subscriptions whose next_billing_date <= today"""
    today = today or date.today().isoformat()
    return query("""SELECT * FROM subscriptions
                    WHERE status='Active' AND next_billing_date<=?""", (today,))


def get_active_discounts(today=None):
    """-> discounts valid today, within usage_limit"""
    today = today or date.today().isoformat()
    return query("""SELECT * FROM discounts WHERE active=1
                    AND (start_date IS NULL OR start_date<=?)
                    AND (end_date IS NULL OR end_date>=?)
                    AND (usage_limit IS NULL OR times_used<usage_limit)""", (today, today))


def get_invoice_paid(invoice_id):
    """-> float total paid so far"""
    return query_one("SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE invoice_id=?",
                     (invoice_id,))["s"]


def record_payment(invoice_id, method, amount, payment_date, note=""):
    """Insert payment; auto-mark invoice 'Paid' when fully paid. -> payment id"""
    pid = insert("payments", {"invoice_id": invoice_id, "method": method,
                              "amount": amount, "payment_date": payment_date, "note": note})
    inv = get_by_id("invoices", invoice_id)
    if inv and get_invoice_paid(invoice_id) >= inv["total_amount"]:
        update("invoices", invoice_id, {"status": "Paid"})
    return pid


# ---------- dashboard helpers (Member 3) ----------
def get_kpis(today=None):
    """-> dict(active_subs, revenue, outstanding, overdue_count)"""
    today = today or date.today().isoformat()
    return {
        "active_subs": query_one("SELECT COUNT(*) n FROM subscriptions WHERE status='Active'")["n"],
        "revenue": query_one("SELECT COALESCE(SUM(amount),0) s FROM payments")["s"],
        "outstanding": query_one("""SELECT COALESCE(SUM(total_amount),0) s FROM invoices
                                    WHERE status IN ('Draft','Confirmed')""")["s"],
        "overdue_count": query_one("""SELECT COUNT(*) n FROM invoices
                                      WHERE status='Confirmed' AND due_date<?""", (today,))["n"],
    }


def get_overdue_invoices(today=None):
    """-> list[dict] overdue invoices"""
    today = today or date.today().isoformat()
    return query("SELECT * FROM invoices WHERE status='Confirmed' AND due_date<? ORDER BY due_date",
                 (today,))


init_db()  # runs on import, so tables always exist