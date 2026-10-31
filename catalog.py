"""catalog.py - Products, plans and subscriptions (Streamlit).

Exports: show_catalog_page()

Role rules
    Admin    -> tabs: Products (edit), Plans, Subscriptions
    Staff    -> tabs: Products (view only), Subscriptions
    Customer -> tab : My Subscriptions (read only)

All database work goes through the helpers in db.py. Nothing runs at import time.
"""
import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import db

STAGES = ["Draft", "Quotation", "Confirmed", "Active", "Closed"]
BILLING_PERIODS = ["Daily", "Weekly", "Monthly", "Yearly"]
STAGE_COLORS = {
    "Draft": "#6b7280",
    "Quotation": "#2563eb",
    "Confirmed": "#d97706",
    "Active": "#16a34a",
    "Closed": "#b91c1c",
}
NEW_LINES_KEY = "ns_lines"       # session key holding the lines of the subscription being built
FLASH_KEY = "catalog_flash"      # session key for a message that must survive st.rerun()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _flash(kind, message):
    """Remember a message (kind = success / error / warning) to show after st.rerun()."""
    st.session_state[FLASH_KEY] = (kind, message)


def _show_flash():
    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        kind, message = flash
        getattr(st, kind)(message)


def _num(value):
    """Turn None / '' into 0.0 so price maths never crashes."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _variant_label(variant):
    return f"{variant['attribute']}: {variant['value']} (+{_num(variant['extra_price']):.2f})"


def _badge_html(status):
    color = STAGE_COLORS.get(status, "#6b7280")
    return (
        f"<span style='background:{color};color:#ffffff;padding:3px 12px;"
        f"border-radius:12px;font-size:0.85rem;font-weight:600;'>{html.escape(str(status))}</span>"
    )


def _progress_row(status):
    """Show the 5 stages in a row, with the current one highlighted."""
    current = STAGES.index(status) if status in STAGES else -1
    for index, (column, stage) in enumerate(zip(st.columns(len(STAGES)), STAGES)):
        base = "padding:6px 4px;border-radius:8px;text-align:center;font-size:0.85rem;"
        if index == current:
            style = base + f"background:{STAGE_COLORS[stage]};color:#ffffff;font-weight:700;"
        elif index < current:
            style = base + "background:rgba(128,128,128,0.25);"
        else:
            style = base + "border:1px dashed rgba(128,128,128,0.6);opacity:0.6;"
        column.markdown(f"<div style='{style}'>{stage}</div>", unsafe_allow_html=True)


def _lines_dataframe(sub_id):
    """Lines of one subscription as a DataFrame (None if there are no lines)."""
    rows = []
    for line in db.get_subscription_lines(sub_id):
        variant_text = "-"
        if line["variant_id"]:
            for variant in db.get_variants(line["product_id"]):
                if variant["id"] == line["variant_id"]:
                    variant_text = f"{variant['attribute']}: {variant['value']}"
        rows.append({
            "Product": line["product_name"],
            "Variant": variant_text,
            "Qty": line["qty"],
            "Unit price": line["unit_price"],
            "Tax %": line["tax_rate"],
            "Amount": line["amount"],
        })
    return pd.DataFrame(rows) if rows else None


# ---------------------------------------------------------------------------
# Products tab
# ---------------------------------------------------------------------------
def _products_tab(can_edit):
    if can_edit:
        st.subheader("Add a product")
        with st.form("product_form", clear_on_submit=True):
            name = st.text_input("Name", key="prod_name")
            product_type = st.text_input("Type", placeholder="e.g. Service, Software", key="prod_type")
            col1, col2 = st.columns(2)
            base_price = col1.number_input("Base price", min_value=0.0, step=1.0, format="%.2f",
                                           key="prod_base_price")
            cost_price = col2.number_input("Cost price", min_value=0.0, step=1.0, format="%.2f",
                                           key="prod_cost_price")
            notes = st.text_area("Notes", key="prod_notes")
            submitted = st.form_submit_button("Add product")

        if submitted:
            if not name.strip():
                st.error("Product name is required.")
            else:
                db.insert("products", {
                    "name": name.strip(),
                    "type": product_type.strip() or None,
                    "base_price": float(base_price),
                    "cost_price": float(cost_price),
                    "notes": notes.strip() or None,
                })
                st.success(f"Product '{name.strip()}' was added.")
    else:
        st.caption("View only. Ask an Admin to change products.")

    # Drawn after the form, so a new product shows up straight away.
    st.subheader("Products")
    products = db.list_all("products")
    if not products:
        st.info("No products yet.")
        return
    st.dataframe(
        pd.DataFrame(products)[["id", "name", "type", "base_price", "cost_price", "notes"]],
        hide_index=True,
    )

    # ---- Variants of one product
    st.subheader("Variants")
    product_map = {p["id"]: p for p in products}
    product_id = st.selectbox(
        "Choose a product", options=list(product_map),
        format_func=lambda pid: f"{product_map[pid]['name']} (#{pid})",
        key="variant_product",
    )
    product_base_price = _num(product_map[product_id]["base_price"])
    st.metric("Base price", f"{product_base_price:.2f}")

    if can_edit:
        with st.form("variant_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            attribute = col1.text_input("Attribute", placeholder="e.g. Brand", key="var_attribute")
            value = col2.text_input("Value", placeholder="e.g. Odoo", key="var_value")
            extra_price = col3.number_input("Extra price", min_value=0.0, step=1.0, format="%.2f",
                                            key="var_extra_price")
            variant_submitted = st.form_submit_button("Add variant")

        if variant_submitted:
            if not attribute.strip() or not value.strip():
                st.error("Attribute and value are both required.")
            else:
                db.insert("product_variants", {
                    "product_id": product_id,
                    "attribute": attribute.strip(),
                    "value": value.strip(),
                    "extra_price": float(extra_price),
                })
                st.success(f"Variant {attribute.strip()}: {value.strip()} was added.")

    variants = db.get_variants(product_id)
    if variants:
        st.dataframe(
            pd.DataFrame([{
                "Attribute": v["attribute"],
                "Value": v["value"],
                "Extra price": _num(v["extra_price"]),
                "Final unit price": round(product_base_price + _num(v["extra_price"]), 2),
            } for v in variants]),
            hide_index=True,
        )
        st.caption("Final unit price = base price + variant extra price.")
    else:
        st.info("This product has no variants yet.")


# ---------------------------------------------------------------------------
# Plans tab (Admin only)
# ---------------------------------------------------------------------------
def _plans_tab():
    st.subheader("Add a plan")
    with st.form("plan_form"):
        col1, col2, col3 = st.columns(3)
        name = col1.text_input("Plan name", key="plan_name")
        price = col2.number_input("Price", min_value=0.0, step=1.0, format="%.2f", key="plan_price")
        period = col3.selectbox("Billing period", BILLING_PERIODS, index=2, key="plan_period")

        col4, col5, col6 = st.columns(3)
        min_qty = col4.number_input("Minimum quantity", min_value=1, value=1, step=1, key="plan_min_qty")
        start_date = col5.date_input("Start date", value=date.today(), key="plan_start")
        end_date = col6.date_input("End date", value=date.today() + timedelta(days=365), key="plan_end")

        col7, col8, col9, col10 = st.columns(4)
        auto_close = col7.checkbox("Auto close", value=False, key="plan_auto_close")
        allow_pause = col8.checkbox("Allow pause", value=True, key="plan_allow_pause")
        allow_renew = col9.checkbox("Allow renew", value=True, key="plan_allow_renew")
        allow_early_close = col10.checkbox("Allow early close", value=True, key="plan_allow_early_close")
        submitted = st.form_submit_button("Add plan")

    if submitted:
        if not name.strip():
            st.error("Plan name is required.")
        elif end_date < start_date:
            st.error("End date cannot be before the start date.")
        else:
            db.insert("plans", {
                "name": name.strip(),
                "price": float(price),
                "billing_period": period,
                "min_qty": int(min_qty),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "auto_close": 1 if auto_close else 0,
                "allow_pause": 1 if allow_pause else 0,
                "allow_renew": 1 if allow_renew else 0,
                "allow_early_close": 1 if allow_early_close else 0,
            })
            st.success(f"Plan '{name.strip()}' was added.")

    st.subheader("Plans")
    plans = db.list_all("plans")
    if not plans:
        st.info("No plans yet.")
        return
    rows = []
    for plan in plans:
        row = dict(plan)
        for flag in ("auto_close", "allow_pause", "allow_renew", "allow_early_close"):
            row[flag] = "Yes" if plan[flag] else "No"
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True)


# ---------------------------------------------------------------------------
# Subscriptions tab (Admin + Staff)
# ---------------------------------------------------------------------------
def _subscriptions_tab():
    _show_flash()

    plans = {p["id"]: p for p in db.list_all("plans")}
    subs = sorted(db.list_all("subscriptions"), key=lambda s: s["id"], reverse=True)

    # ---- Search + status filter + table
    col1, col2 = st.columns([2, 1])
    search = col1.text_input("Search by number or customer email", key="sub_search").strip().lower()
    status_filter = col2.selectbox("Status", ["All"] + STAGES, key="sub_status_filter")

    shown = []
    for sub in subs:
        if status_filter != "All" and sub["status"] != status_filter:
            continue
        if search and search not in (sub["number"] or "").lower() \
                and search not in (sub["customer_email"] or "").lower():
            continue
        shown.append(sub)

    if shown:
        st.dataframe(
            pd.DataFrame([{
                "Number": s["number"],
                "Customer": s["customer_email"],
                "Plan": plans.get(s["plan_id"], {}).get("name", "-"),
                "Status": s["status"],
                "Start": s["start_date"],
                "Expiry": s["expiry_date"],
                "Payment terms": s["payment_terms"],
                "Total": s["total_amount"],
                "Next billing": s["next_billing_date"],
            } for s in shown]),
            hide_index=True,
        )
    else:
        st.info("No subscriptions match.")

    _new_subscription_section(plans)
    _lifecycle_section(subs)


def _new_subscription_section(plans):
    with st.expander("New subscription"):
        customers = sorted(u["email"] for u in db.list_all("users", role="Customer"))
        products = db.list_all("products")
        taxes = db.list_all("taxes")

        if not customers:
            st.info("There are no customers yet. A customer must sign up first.")
            return
        if not plans:
            st.info("There are no plans yet. Ask an Admin to create a plan first.")
            return
        if not products:
            st.info("There are no products yet. Ask an Admin to add a product first.")
            return

        # ---- Header fields
        col1, col2 = st.columns(2)
        customer = col1.selectbox("Customer email", customers, key="ns_customer")
        plan_id = col2.selectbox(
            "Plan", options=list(plans),
            format_func=lambda pid: f"{plans[pid]['name']} ({plans[pid]['billing_period']})",
            key="ns_plan",
        )
        col3, col4, col5 = st.columns(3)
        start_date = col3.date_input("Start date", value=date.today(), key="ns_start")
        expiry_date = col4.date_input("Expiry date", value=date.today() + timedelta(days=365),
                                      key="ns_expiry")
        payment_terms = col5.text_input("Payment terms", value="Net 30", key="ns_terms")

        # ---- Line builder
        st.markdown("**Add lines**")
        product_map = {p["id"]: p for p in products}
        tax_map = {t["id"]: t for t in taxes}

        lcol1, lcol2, lcol3, lcol4 = st.columns(4)
        product_id = lcol1.selectbox(
            "Product", options=list(product_map),
            format_func=lambda pid: product_map[pid]["name"], key="ns_product",
        )
        variants = {v["id"]: v for v in db.get_variants(product_id)}
        variant_id = lcol2.selectbox(  # 0 means "no variant"
            "Variant (optional)", options=[0] + list(variants),
            format_func=lambda vid: "None" if vid == 0 else _variant_label(variants[vid]),
            key=f"ns_variant_{product_id}",   # new key per product, so the choice resets
        )
        qty = lcol3.number_input("Quantity", min_value=1, value=1, step=1, key="ns_qty")
        tax_id = lcol4.selectbox(  # 0 means "no tax"
            "Tax", options=[0] + list(tax_map),
            format_func=lambda tid: "No tax" if tid == 0 else f"{tax_map[tid]['name']} ({tax_map[tid]['rate']}%)",
            key="ns_tax",
        )

        lines = st.session_state.setdefault(NEW_LINES_KEY, [])

        if st.button("Add line", key="ns_add_line"):
            extra = _num(variants[variant_id]["extra_price"]) if variant_id else 0.0
            unit_price = round(_num(product_map[product_id]["base_price"]) + extra, 2)
            lines.append({
                "product_id": product_id,
                "product_name": product_map[product_id]["name"],
                "variant_id": variant_id,
                "variant_text": _variant_label(variants[variant_id]) if variant_id else "-",
                "qty": int(qty),
                "unit_price": unit_price,
                "tax_id": tax_id,
                "tax_text": f"{tax_map[tax_id]['name']} ({tax_map[tax_id]['rate']}%)" if tax_id else "No tax",
                "amount": round(int(qty) * unit_price, 2),
            })

        if lines:
            st.dataframe(
                pd.DataFrame([{
                    "Product": ln["product_name"], "Variant": ln["variant_text"],
                    "Qty": ln["qty"], "Unit price": ln["unit_price"],
                    "Tax": ln["tax_text"], "Amount": ln["amount"],
                } for ln in lines]),
                hide_index=True,
            )
            st.write(f"**Total: {sum(ln['amount'] for ln in lines):.2f}**")
        else:
            st.caption("No lines added yet.")

        # ---- Save
        if st.button("Save subscription", type="primary", key="ns_save"):
            problems = []
            if not lines:
                problems.append("Add at least one line before saving.")
            if expiry_date < start_date:
                problems.append("Expiry date cannot be before the start date.")
            if problems:
                for problem in problems:
                    st.error(problem)
                return

            try:
                number = db.next_sub_number()
                total = round(sum(ln["amount"] for ln in lines), 2)
                sub_id = db.insert("subscriptions", {
                    "number": number,
                    "customer_email": customer,
                    "plan_id": plan_id,
                    "status": "Draft",
                    "start_date": start_date.isoformat(),
                    "expiry_date": expiry_date.isoformat(),
                    "payment_terms": payment_terms.strip() or None,
                    "total_amount": total,
                    "next_billing_date": start_date.isoformat(),
                })
                for ln in lines:
                    db.insert("subscription_lines", {
                        "subscription_id": sub_id,
                        "product_id": ln["product_id"],
                        "variant_id": ln["variant_id"] or None,
                        "qty": ln["qty"],
                        "unit_price": ln["unit_price"],
                        "tax_id": ln["tax_id"] or None,
                        "amount": ln["amount"],
                    })
            except Exception as exc:
                st.error(f"Could not save the subscription: {exc}")
                return

            st.session_state[NEW_LINES_KEY] = []
            _flash("success", f"Subscription {number} was created as Draft (total {total:.2f}).")
            st.rerun()


def _lifecycle_section(subs):
    st.subheader("Lifecycle")
    if not subs:
        st.info("No subscriptions yet.")
        return

    labels = {s["id"]: f"{s['number']} - {s['customer_email']}" for s in subs}
    sub_id = st.selectbox("Select a subscription", options=list(labels),
                          format_func=lambda sid: labels[sid], key="life_sub")
    sub = db.get_by_id("subscriptions", sub_id)
    status = sub["status"]

    st.markdown(_badge_html(status), unsafe_allow_html=True)
    if status not in STAGES:
        st.error(f"Unknown status '{status}'. It cannot be moved.")
        return
    _progress_row(status)

    position = STAGES.index(status)
    if position == len(STAGES) - 1:
        st.caption("This subscription is Closed. There is no next stage.")
    else:
        next_status = STAGES[position + 1]          # ONLY the very next stage is possible
        if st.button(f"Move to {next_status}", key=f"advance_{sub_id}"):
            latest = db.get_by_id("subscriptions", sub_id)["status"]
            if latest != status:                    # someone else changed it meanwhile
                _flash("warning", f"{sub['number']} was changed by someone else. Please check it again.")
            else:
                db.update("subscriptions", sub_id, {"status": next_status})
                _flash("success", f"{sub['number']} moved from {status} to {next_status}.")
            st.rerun()


# ---------------------------------------------------------------------------
# Customer view
# ---------------------------------------------------------------------------
def _my_subscriptions_tab(user):
    subs = sorted(db.list_all("subscriptions", customer_email=user["email"]),
                  key=lambda s: s["id"], reverse=True)
    if not subs:
        st.info("You do not have any subscriptions yet.")
        return

    plans = {p["id"]: p for p in db.list_all("plans")}
    for sub in subs:
        with st.expander(f"{sub['number']} - {sub['status']} - total {_num(sub['total_amount']):.2f}"):
            st.markdown(_badge_html(sub["status"]), unsafe_allow_html=True)
            st.write(
                f"Plan: {plans.get(sub['plan_id'], {}).get('name', '-')}  \n"
                f"Start: {sub['start_date'] or '-'}  |  Expiry: {sub['expiry_date'] or '-'}  \n"
                f"Payment terms: {sub['payment_terms'] or '-'}  \n"
                f"Next billing: {sub['next_billing_date'] or '-'}"
            )
            lines_df = _lines_dataframe(sub["id"])
            if lines_df is not None:
                st.dataframe(lines_df, hide_index=True)
            else:
                st.caption("No lines on this subscription.")


# ---------------------------------------------------------------------------
# Page entry point
# ---------------------------------------------------------------------------
def show_catalog_page():
    user = st.session_state.get("user")
    if not user:
        st.error("Please log in to see this page.")
        return

    role = user.get("role")
    st.title("Catalog and subscriptions")

    if role == "Admin":
        products_tab, plans_tab, subs_tab = st.tabs(["Products", "Plans", "Subscriptions"])
        with products_tab:
            _products_tab(can_edit=True)
        with plans_tab:
            _plans_tab()
        with subs_tab:
            _subscriptions_tab()
    elif role == "Staff":
        products_tab, subs_tab = st.tabs(["Products", "Subscriptions"])
        with products_tab:
            _products_tab(can_edit=False)
        with subs_tab:
            _subscriptions_tab()
    elif role == "Customer":
        (my_tab,) = st.tabs(["My Subscriptions"])
        with my_tab:
            _my_subscriptions_tab(user)
    else:
        st.error("Your account role is not recognised. Please contact an Admin.")