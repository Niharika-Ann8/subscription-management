import sqlite3
import datetime
import calendar
import streamlit as st
import  db

# -----------------------------------------------------------------------------
# CONSTANTS & UTILITIES
# -----------------------------------------------------------------------------

def add_billing_period(start_date: datetime.date, period: str) -> datetime.date:
    """Calculates the next billing date based on plan period with month length clamping."""
    p = (period or 'Monthly').capitalize()
    if p == 'Daily':
        return start_date + datetime.timedelta(days=1)
    elif p == 'Weekly':
        return start_date + datetime.timedelta(weeks=1)
    elif p == 'Monthly':
        year = start_date.year + (start_date.month // 12)
        month = (start_date.month % 12) + 1
        day = start_date.day
        max_days = calendar.monthrange(year, month)[1]
        return datetime.date(year, month, min(day, max_days))
    elif p == 'Yearly':
        year = start_date.year + 1
        month = start_date.month
        day = start_date.day
        max_days = calendar.monthrange(year, month)[1]
        return datetime.date(year, month, min(day, max_days))
    else:
        return start_date + datetime.timedelta(days=30)


# -----------------------------------------------------------------------------
# PURE LOGIC FUNCTIONS (No st.* calls allowed)
# -----------------------------------------------------------------------------

def best_discount(lines: list, discounts: list):
    """
    Evaluates active discounts against subscription lines.
    Returns tuple: (best_discount_obj, best_discount_amount)
    """
    best_disc = None
    max_disc_amount = 0.0

    for disc in discounts:
        if disc.get('active') is not None and not disc['active']:
            continue

        usage_limit = disc.get('usage_limit')
        times_used = disc.get('times_used', 0) or 0
        if usage_limit is not None and usage_limit > 0 and times_used >= usage_limit:
            continue

        prod_id = disc.get('product_id')
        if prod_id is not None:
            matching_lines = [l for l in lines if l.get('product_id') == prod_id]
        else:
            matching_lines = lines

        pool_base = sum(float(l.get('amount', 0)) for l in matching_lines)
        pool_qty = sum(int(l.get('qty', 0)) for l in matching_lines)

        min_qty = disc.get('min_qty') or 0
        min_amount = disc.get('min_amount') or 0.0

        if pool_qty < min_qty or pool_base < min_amount:
            continue

        disc_type = disc.get('type') or 'Percentage'
        val = float(disc.get('value', 0))

        if disc_type == 'Percentage':
            calc_amount = round(pool_base * (val / 100.0), 2)
        elif disc_type == 'Fixed':
            calc_amount = round(min(val, pool_base), 2)
        else:
            calc_amount = 0.0

        if calc_amount > max_disc_amount:
            max_disc_amount = calc_amount
            best_disc = disc

    return best_disc, max_disc_amount


def bill_subscription(sub: dict, today_str: str):
    """
    Bills a single subscription. Creates Draft invoice and invoice lines,
    updates discount usage, and advances next_billing_date.
    """
    period_start = sub.get('next_billing_date') or today_str

    # Check if an invoice for this subscription and period_start already exists
    existing = db.query(
        "SELECT id FROM invoices WHERE subscription_id = ? AND period_start = ?", 
        (sub['id'], str(period_start))
    )
    if existing:
        return {"status": "already_billed"}

    lines = db.get_subscription_lines(sub['id'])
    base_amount = sum(float(l.get('amount', 0)) for l in lines)
    tax_amount = sum(round(float(l.get('amount', 0)) * float(l.get('tax_rate', 0)) / 100.0, 2) for l in lines)

    active_discounts = db.get_active_discounts(today_str)
    best_disc, disc_amount = best_discount(lines, active_discounts)

    base_amount = round(base_amount, 2)
    tax_amount = round(tax_amount, 2)
    disc_amount = round(disc_amount, 2)
    total_amount = round(base_amount + tax_amount - disc_amount, 2)

    terms_str = str(sub.get('payment_terms', ''))
    digits = ''.join(c for c in terms_str if c.isdigit())
    days = int(digits) if digits else 0

    p_start_date = datetime.date.fromisoformat(str(period_start))
    due_date = (p_start_date + datetime.timedelta(days=days)).isoformat()

    # Insert Invoice
    inv_id = db.insert("invoices", {
        "subscription_id": sub['id'],
        "customer_email": sub.get('customer_email', ''),
        "base_amount": base_amount,
        "tax_amount": tax_amount,
        "discount_amount": disc_amount,
        "total_amount": total_amount,
        "status": "Draft",
        "due_date": due_date,
        "period_start": str(period_start)
    })

    # Insert Invoice Lines
    for line in lines:
        l_amount = float(line.get('amount', 0))
        l_tax = round(l_amount * float(line.get('tax_rate', 0)) / 100.0, 2)
        db.insert("invoice_lines", {
            "invoice_id": inv_id,
            "product_id": line.get('product_id'),
            "description": line.get('product_name') or f"Product #{line.get('product_id')}",
            "qty": line.get('qty', 1),
            "unit_price": line.get('unit_price', l_amount),
            "tax_amount": l_tax,
            "amount": l_amount
        })

    # Update discount times_used AFTER invoice succeeds
    if best_disc and best_disc.get('id'):
        db.execute("UPDATE discounts SET times_used = times_used + 1 WHERE id = ?", (best_disc['id'],))

    # Update subscription next_billing_date
    plan_id = sub.get('plan_id')
    plan = db.get_by_id("plans", plan_id) if plan_id else None
    billing_period = plan.get('billing_period', 'Monthly') if plan else 'Monthly'

    new_next_date = add_billing_period(p_start_date, billing_period)
    expiry_str = sub.get('expiry_date')
    if expiry_str:
        exp_date = datetime.date.fromisoformat(str(expiry_str))
        new_next_date_str = None if new_next_date > exp_date else new_next_date.isoformat()
    else:
        new_next_date_str = new_next_date.isoformat()

    db.update("subscriptions", sub['id'], {"next_billing_date": new_next_date_str})

    return {"status": "created", "invoice_id": inv_id}


def run_billing(today=None):
    """
    Runs the automated billing engine for all due subscriptions.
    Returns dict: {"created": n, "already_billed": n, "rows": [...], "errors": [...]}
    """
    today_str = str(today) if today else datetime.date.today().isoformat()

    created = 0
    already_billed = 0
    rows = []
    errors = []

    due_subs = db.get_due_subscriptions(today_str)
    all_subs = db.list_all("subscriptions")
    processed_ids = set()

    for sub in due_subs:
        processed_ids.add(sub['id'])
        try:
            res = bill_subscription(sub, today_str)
            if res["status"] == "created":
                created += 1
                rows.append({"subscription_id": sub['id'], "status": "Created", "invoice_id": res["invoice_id"]})
            elif res["status"] == "already_billed":
                already_billed += 1
                rows.append({"subscription_id": sub['id'], "status": "Already Billed"})
        except sqlite3.IntegrityError:
            already_billed += 1
            rows.append({"subscription_id": sub['id'], "status": "Already Billed"})
        except Exception as e:
            errors.append(f"Sub #{sub['id']}: {str(e)}")

    for sub in all_subs:
        if sub['id'] not in processed_ids and sub.get('status') == 'Active':
            invs = db.query(
                "SELECT id FROM invoices WHERE subscription_id = ?", 
                (sub['id'],)
            )
            if invs:
                already_billed += 1
                rows.append({"subscription_id": sub['id'], "status": "Already Billed"})

    return {
        "created": created,
        "already_billed": already_billed,
        "rows": rows,
        "errors": errors
    }


# -----------------------------------------------------------------------------
# STREAMLIT UI RENDER FUNCTION
# -----------------------------------------------------------------------------

def show_billing_page():
    user = st.session_state.get("user", {})
    role = user.get("role") if isinstance(user, dict) else getattr(user, "role", None)

    if role not in ["Admin", "Staff"]:
        st.error("Access denied. Admin or Staff permission required.")
        return

    st.title("Billing, Payments & Finance")

    if role == "Admin":
        tab_run, tab_payments, tab_invoices, tab_discounts = st.tabs([
            "Billing Run", "Payments", "Invoices", "Discounts"
        ])
    else:
        tab_run, tab_payments, tab_invoices = st.tabs([
            "Billing Run", "Payments", "Invoices"
        ])
        tab_discounts = None

    # Tab 1: Billing Run
    with tab_run:
        st.header("Billing Engine Run")
        st.write("Generate Draft invoices for all active due subscriptions.")
        if st.button("Run Billing Engine"):
            res = run_billing()
            if res["errors"]:
                for err in res["errors"]:
                    st.error(err)
            st.success(f"Created {res['created']} Draft invoice(s). {res['already_billed']} already billed.")
            if res["rows"]:
                st.dataframe(res["rows"], width="stretch")

    # Tab 2: Payments
    with tab_payments:
        st.header("Payment Processing")
        confirmed_invoices = db.query("SELECT * FROM invoices WHERE status = 'Confirmed'")
        
        if not confirmed_invoices:
            st.info("No confirmed invoices available for payment.")
        else:
            inv_map = {}
            for inv in confirmed_invoices:
                paid = db.get_invoice_paid(inv['id'])
                bal = round(float(inv['total_amount']) - float(paid), 2)
                inv_map[inv['id']] = (inv, bal)
                
            options = {
                inv_id: f"Invoice #{inv_id} ({inv['customer_email']}) - Total: ${inv['total_amount']:.2f} | Balance: ${bal:.2f}"
                for inv_id, (inv, bal) in inv_map.items()
            }
            selected_id = st.selectbox("Select Confirmed Invoice", list(options.keys()), format_func=lambda x: options[x])
            
            if selected_id:
                sel_inv, bal = inv_map[selected_id]
                with st.form("payment_form"):
                    method = st.selectbox("Payment Method", ["UPI", "Card", "Bank Transfer"])
                    pay_amount = st.number_input(
                        "Amount", 
                        min_value=0.01, 
                        max_value=float(bal) if bal > 0 else 0.01, 
                        value=float(bal) if bal > 0 else 0.01, 
                        step=0.01
                    )
                    pay_date = st.date_input("Payment Date", value=datetime.date.today())
                    note = st.text_input("Transaction Note / Ref", placeholder="e.g. TXN123456")
                    submitted = st.form_submit_button("Record Payment")
                    
                    if submitted:
                        if pay_amount <= 0:
                            st.error("Payment amount must be greater than 0.")
                        elif round(pay_amount - bal, 2) > 0.001:
                            st.error(f"Amount cannot exceed outstanding balance of ${bal:.2f}.")
                        else:
                            db.record_payment(selected_id, method, pay_amount, str(pay_date), note)
                            new_paid = db.get_invoice_paid(selected_id)
                            rem_bal = round(float(sel_inv['total_amount']) - float(new_paid), 2)
                            if rem_bal <= 0 and sel_inv['status'] != 'Paid':
                                db.update("invoices", selected_id, {"status": "Paid"})
                                st.success(f"Payment recorded! Invoice #{selected_id} is now Paid.")
                            else:
                                st.success(f"Partial payment of ${pay_amount:.2f} recorded. Remaining balance: ${rem_bal:.2f}.")
                            st.rerun()

    # Tab 3: Invoices
    with tab_invoices:
        st.header("Invoice Management")
        col1, col2 = st.columns([3, 1])
        with col2:
            if st.button("Confirm All Drafts"):
                db.execute("UPDATE invoices SET status = 'Confirmed' WHERE status = 'Draft'")
                st.success("All draft invoices confirmed!")
                st.rerun()
                
        all_invoices = db.list_all("invoices")
        if all_invoices:
            st.dataframe(all_invoices, width="stretch")
            drafts = [inv for inv in all_invoices if inv.get('status') == 'Draft']
            if drafts:
                st.subheader("Confirm Individual Draft Invoice")
                draft_options = {inv['id']: f"Invoice #{inv['id']} - ${inv['total_amount']:.2f} ({inv['customer_email']})" for inv in drafts}
                selected_draft_id = st.selectbox("Select Draft Invoice", list(draft_options.keys()), format_func=lambda x: draft_options[x])
                if st.button("Confirm Selected Invoice"):
                    db.update("invoices", selected_draft_id, {"status": "Confirmed"})
                    st.success(f"Invoice #{selected_draft_id} updated to Confirmed!")
                    st.rerun()

    # Tab 4: Discounts (Admin Only)
    if tab_discounts and role == "Admin":
        with tab_discounts:
            st.header("Discount Management (Admin Only)")
            today_date = datetime.date.today()
            
            with st.form("create_discount_form"):
                st.subheader("Create New Discount")
                col_a, col_b = st.columns(2)
                with col_a:
                    code = st.text_input("Discount Code", placeholder="e.g. SUMMER10")
                    disc_type = st.selectbox("Type", ["Percentage", "Fixed"])
                    val = st.number_input("Value", min_value=0.0, step=1.0)
                    product_id_input = st.number_input("Product ID (0 for all)", min_value=0, step=1)
                with col_b:
                    min_qty = st.number_input("Min Quantity", min_value=0, step=1)
                    min_amount = st.number_input("Min Base Amount ($)", min_value=0.0, step=1.0)
                    usage_limit = st.number_input("Usage Limit (0 for unlimited)", min_value=0, step=1)
                    
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    start_date = st.date_input("Start Date", value=today_date)
                with col_d2:
                    end_date = st.date_input("End Date", value=today_date + datetime.timedelta(days=30))
                    
                submitted = st.form_submit_button("Create Discount")
                
                if submitted:
                    code_clean = code.strip()
                    if not code_clean:
                        st.error("Discount code cannot be empty.")
                    elif val <= 0:
                        st.error("Discount value must be greater than 0.")
                    elif disc_type == "Percentage" and val > 100:
                        st.error("Percentage discount value cannot exceed 100%.")
                    elif end_date < start_date:
                        st.error("End date must be greater than or equal to start date.")
                    else:
                        p_id = int(product_id_input) if product_id_input > 0 else None
                        u_limit = int(usage_limit) if usage_limit > 0 else None
                        db.insert("discounts", {
                            "code": code_clean,
                            "type": disc_type,
                            "value": float(val),
                            "min_qty": int(min_qty),
                            "min_amount": float(min_amount),
                            "start_date": str(start_date),
                            "end_date": str(end_date),
                            "usage_limit": u_limit,
                            "times_used": 0,
                            "product_id": p_id,
                            "active": 1
                        })
                        st.success(f"Discount '{code_clean}' created!")
                        st.rerun()

            st.subheader("Existing Discounts")
            discounts = db.list_all("discounts")
            if discounts:
                formatted_discounts = []
                for d in discounts:
                    d_copy = dict(d)
                    active = d_copy.get('active', 1)
                    s_date = d_copy.get('start_date')
                    e_date = d_copy.get('end_date')
                    u_limit = d_copy.get('usage_limit')
                    t_used = d_copy.get('times_used', 0) or 0
                    
                    if not active:
                        state = "Inactive"
                    elif e_date and str(today_date) > str(e_date):
                        state = "Expired"
                    elif s_date and str(today_date) < str(s_date):
                        state = "Scheduled"
                    elif u_limit is not None and u_limit > 0 and t_used >= u_limit:
                        state = "Exhausted"
                    else:
                        state = "Active"
                        
                    d_copy["state"] = state
                    formatted_discounts.append(d_copy)
                    
                st.dataframe(formatted_discounts, width="stretch")