
"""app.py - Brightloop Subscription Management System (entry point).

Only this file calls st.set_page_config. Teammate pages are imported lazily so a
missing or broken page shows "coming soon" instead of crashing the app.
"""
import importlib
import time
from datetime import date

import pandas as pd
import streamlit as st

import db

st.set_page_config(page_title="Brightloop Subscriptions", page_icon="🔁", layout="wide")

MENUS = {
    "Admin": ["Dashboard", "Catalog & Subscriptions", "Billing", "Staff Management"],
    "Staff": ["Dashboard", "Catalog & Subscriptions", "Billing"],
    "Customer": ["My Subscriptions", "My Invoices"],
}

# ---------------------------------------------------------------- helpers
def _load(module, attr):
    """-> (function, None) or (None, error text)."""
    try:
        return getattr(importlib.import_module(module), attr), None
    except Exception as exc:  # missing file, missing function, import-time crash
        return None, f"{type(exc).__name__}: {exc}"


def _run_teammate(module, attr, label):
    fn, err = _load(module, attr)
    if fn is None:
        st.info(f"{label} is coming soon.")
        with st.expander("Details"):
            st.code(err or "unknown error")
        return
    try:
        fn()
    except Exception as exc:
        st.error(f"{label} failed to load.")
        st.exception(exc)


def _logout():
    fn, _ = _load("auth", "logout")
    if fn:
        fn()
    else:
        for key in list(st.session_state.keys()):
            del st.session_state[key]


def _money(v):
    return f"₹{v:,.2f}"


# ---------------------------------------------------------------- queries
INV_SELECT = """
SELECT i.id AS invoice, s.number AS subscription, i.customer_email AS customer,
       i.status, i.due_date, i.total_amount AS total,
       ROUND(COALESCE(p.paid,0),2) AS paid,
       ROUND(i.total_amount - COALESCE(p.paid,0),2) AS balance,
       CASE WHEN i.status='Confirmed' AND i.due_date<? THEN 'OVERDUE' ELSE '' END AS flag
FROM invoices i
LEFT JOIN subscriptions s ON s.id=i.subscription_id
LEFT JOIN (SELECT invoice_id, SUM(amount) AS paid FROM payments GROUP BY invoice_id) p
       ON p.invoice_id=i.id
"""

OUTSTANDING_SQL = """
SELECT COALESCE(SUM(i.total_amount - COALESCE(p.paid,0)),0) AS s
FROM invoices i
LEFT JOIN (SELECT invoice_id, SUM(amount) AS paid FROM payments GROUP BY invoice_id) p
       ON p.invoice_id=i.id
WHERE i.status IN ('Draft','Confirmed')
"""


def _invoices(today, where="", params=(), order="i.due_date, i.id"):
    sql = INV_SELECT + (f" WHERE {where}" if where else "") + f" ORDER BY {order}"
    return pd.DataFrame(db.query(sql, (today, *params)))


def _highlight(row):
    style = "background-color:#ffd6d6;color:#7a0000" if row["flag"] == "OVERDUE" else ""
    return [style] * len(row)


def _show_invoices(df, empty_msg="No invoices match."):
    if df.empty:
        st.info(empty_msg)
        return
    styled = df.style.apply(_highlight, axis=1).format(
        {"total": "{:,.2f}", "paid": "{:,.2f}", "balance": "{:,.2f}"})
    st.dataframe(styled, hide_index=True, width="stretch")


def _clauses(date_col, cust_col, d_from, d_to, search):
    where, params = [], []
    if date_col and d_from:
        where.append(f"{date_col}>=?")
        params.append(d_from.isoformat())
    if date_col and d_to:
        where.append(f"{date_col}<=?")
        params.append(d_to.isoformat())
    if search.strip():
        where.append(f"LOWER({cust_col}) LIKE ?")
        params.append(f"%{search.strip().lower()}%")
    return where, params


def _group(sql, where, params, tail):
    if where:
        sql += " WHERE " + " AND ".join(where)
    return pd.DataFrame(db.query(sql + " " + tail, tuple(params)))


def _summary(title, df, label, value):
    st.markdown(f"**{title}**")
    if df.empty:
        st.caption("No data.")
        return
    st.bar_chart(df.set_index(label)[value])
    st.dataframe(df, hide_index=True, width="stretch")


# ---------------------------------------------------------------- pages
def dashboard():
    t0 = time.perf_counter()
    today = date.today().isoformat()
    st.title("Finance dashboard")

    k = db.get_kpis(today)
    outstanding = db.query_one(OUTSTANDING_SQL)["s"]  # net of partial payments
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Active subscriptions", k["active_subs"])
    c2.metric("Revenue collected", _money(k["revenue"]))
    c3.metric("Outstanding", _money(round(outstanding, 2)))
    c4.metric("Overdue invoices", k["overdue_count"])

    st.subheader("Overdue invoices")
    _show_invoices(
        _invoices(today, "i.status='Confirmed' AND i.due_date<?", (today,), "i.due_date"),
        "No overdue invoices.")

    st.subheader("Invoices")
    f1, f2, f3, f4 = st.columns([1, 1, 1, 2])
    status = f1.selectbox("Invoice status", ["All", "Draft", "Confirmed", "Paid", "Cancelled"])
    d_from = f2.date_input("From", value=None, help="Filters invoice due date and payment date")
    d_to = f3.date_input("To", value=None)
    search = f4.text_input("Customer search", placeholder="email contains...")

    where, params = _clauses("i.due_date", "i.customer_email", d_from, d_to, search)
    if status != "All":
        where.append("i.status=?")
        params.append(status)
    _show_invoices(_invoices(today, " AND ".join(where), params, "i.due_date DESC, i.id DESC"))

    st.subheader("Summary")
    s1, s2, s3 = st.columns(3)

    w, p = _clauses("p.payment_date", "i.customer_email", d_from, d_to, search)
    by_method = _group(
        "SELECT p.method AS method, ROUND(SUM(p.amount),2) AS revenue, COUNT(*) AS payments "
        "FROM payments p LEFT JOIN invoices i ON i.id=p.invoice_id", w, p,
        "GROUP BY p.method ORDER BY revenue DESC")
    with s1:
        _summary("Revenue by payment method", by_method, "method", "revenue")

    w, p = _clauses(None, "customer_email", None, None, search)
    subs = _group("SELECT status, COUNT(*) AS subscriptions FROM subscriptions", w, p,
                  "GROUP BY status ORDER BY subscriptions DESC")
    with s2:
        _summary("Subscriptions by status", subs, "status", "subscriptions")

    w, p = _clauses("due_date", "customer_email", d_from, d_to, search)
    inv = _group("SELECT status, COUNT(*) AS invoices, ROUND(SUM(total_amount),2) AS total "
                 "FROM invoices", w, p, "GROUP BY status ORDER BY invoices DESC")
    with s3:
        _summary("Invoices by status", inv, "status", "invoices")

    st.subheader("Recent payments")
    recent = pd.DataFrame(db.query(
        "SELECT p.id AS payment, p.payment_date AS date, p.invoice_id AS invoice, "
        "i.customer_email AS customer, p.method, p.amount, p.note "
        "FROM payments p LEFT JOIN invoices i ON i.id=p.invoice_id "
        "ORDER BY p.payment_date DESC, p.id DESC LIMIT 10"))
    if recent.empty:
        st.info("No payments yet.")
    else:
        st.dataframe(recent.style.format({"amount": "{:,.2f}"}), hide_index=True, width="stretch")

    st.caption(f"Page built in {(time.perf_counter() - t0) * 1000:.0f} ms")


def my_subscriptions(email):
    st.title("My subscriptions")
    df = pd.DataFrame(db.query(
        "SELECT s.number, p.name AS plan, s.status, s.start_date, s.expiry_date, "
        "s.payment_terms, s.total_amount AS total, s.next_billing_date AS next_billing "
        "FROM subscriptions s LEFT JOIN plans p ON p.id=s.plan_id "
        "WHERE LOWER(s.customer_email)=? ORDER BY s.id", (email.lower(),)))
    if df.empty:
        st.info("You do not have any subscriptions yet.")
        return
    st.dataframe(df.style.format({"total": "{:,.2f}"}), hide_index=True, width="stretch")


def my_invoices(email):
    st.title("My invoices")
    today = date.today().isoformat()
    df = _invoices(today, "LOWER(i.customer_email)=? AND i.status!='Draft'", (email.lower(),), "i.due_date DESC, i.id DESC")
    if not df.empty:
        df = df.drop(columns=["customer"])
    _show_invoices(df, "You do not have any invoices yet.")


# ---------------------------------------------------------------- login gate
user = st.session_state.get("user")
if not user:
    fn, err = _load("auth", "show_auth_page")
    if fn is None:
        st.error("Login page is not available yet.")
        st.code(err or "unknown error")
        st.stop()
    fn()
    if st.session_state.get("user"):
        st.rerun()
    st.stop()

role = user.get("role")
if role not in MENUS:
    st.error(f"Unknown role: {role}")
    st.stop()

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### Brightloop")
    st.caption(f"{user['email']}  ·  {role}")
    page = st.radio("Go to", MENUS[role], key="nav_page")
    st.divider()
    if st.button("Log out", key="logout_btn"):
        _logout()
        st.rerun()

# ---------------------------------------------------------------- router
if page not in MENUS[role]:
    st.error("You do not have access to this page.")
    st.stop()

if page == "Dashboard":
    dashboard()
elif page == "Catalog & Subscriptions":
    _run_teammate("catalog", "show_catalog_page", "Catalog and subscriptions")
elif page == "Billing":
    _run_teammate("billing", "show_billing_page", "Billing")
elif page == "Staff Management":
    _run_teammate("auth", "show_staff_page", "Staff management")
elif page == "My Subscriptions":
    my_subscriptions(user["email"])
elif page == "My Invoices":
    my_invoices(user["email"])