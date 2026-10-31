import streamlit as st
import db
from datetime import datetime, date

# 1. Page Configuration & Green Palette Injection
st.set_page_config(page_title="Billing & Finance Operations", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #E3EED4; color: #0F2A1D; }
    [data-testid="stSidebar"] { background-color: #AEC3B0; }
    h1, h2, h3, h4 { color: #0F2A1D !important; font-weight: 700; }
    
    .stButton > button {
        background-color: #375534 !important;
        color: #FFFFFF !important;
        border-radius: 8px !important;
        border: none !important;
        padding: 0.5rem 1rem !important;
        font-weight: 600 !important;
    }
    .stButton > button:hover {
        background-color: #0F2A1D !important;
        color: #E3EED4 !important;
    }
    
    button[aria-selected="true"] {
        color: #0F2A1D !important;
        border-bottom-color: #375534 !important;
        font-weight: bold !important;
    }
    
    [data-testid="stMetric"] {
        background-color: #AEC3B0;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #6B9071;
    }
    [data-testid="stMetricValue"] { color: #0F2A1D !important; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

st.title("💳 Billing & Finance Operations")

tab1, tab2, tab3, tab4 = st.tabs([
    "🏷️ Manage Discounts", 
    "⚡ Billing Day Run", 
    "💵 Record Payments", 
    "📈 Finance Dashboard"
])

# ==========================================
# TAB 1: MANAGING DISCOUNT RULES
# ==========================================
with tab1:
    st.subheader("Create Discount Rule")
    st.write("Admin tool to configure percentage or fixed discount policies.")
    
    with st.form("discount_rule_form"):
        col1, col2 = st.columns(2)
        with col1:
            code = st.text_input("Discount Code/Name", placeholder="e.g., BULK10")
            disc_type = st.selectbox("Discount Type", ["Percentage", "Fixed"])
            value = st.number_input("Discount Value", min_value=0.0, value=10.0)
            min_qty = st.number_input("Minimum Quantity", min_value=1, value=1)
        with col2:
            min_amount = st.number_input("Minimum Order Amount (₹)", min_value=0.0, value=0.0)
            usage_limit = st.number_input("Usage Limit", min_value=1, value=100)
            start_date = st.date_input("Start Date", date.today())
            end_date = st.date_input("End Date", date.today())
            
        submitted = st.form_submit_button("Save Discount Rule")
        
        if submitted:
            if not code.strip():
                st.error("Please provide a valid discount code name.")
            else:
                db.insert("discounts", {
                    "code": code.upper().strip(),
                    "type": disc_type,
                    "value": value,
                    "min_qty": min_qty,
                    "min_amount": min_amount,
                    "usage_limit": usage_limit,
                    "times_used": 0,
                    "active": 1,
                    "start_date": str(start_date),
                    "end_date": str(end_date)
                })
                st.success(f"Discount '{code.upper()}' created successfully!")
                st.rerun()

    st.divider()
    st.subheader("Active Discount Catalog")
    discounts = db.list_all("discounts")
    if discounts:
        st.dataframe(discounts, use_container_width=True)
    else:
        st.info("No discount rules configured yet.")

# ==========================================
# TAB 2: AUTOMATED BILLING DAY RUNNER
# ==========================================
with tab2:
    st.subheader("⚡ Automated Billing Day Engine")
    st.write("Automatically create draft invoices for due subscriptions.")
    
    today_str = str(date.today())
    due_subs = db.get_due_subscriptions(today_str)
    
    col_a, col_b = st.columns([3, 1])
    with col_a:
        st.write(f"Subscriptions Due for Billing Today ({today_str}): **{len(due_subs)}**")
    with col_b:
        if st.button("➕ Seed Test Subscription"):
            # Inserts mock active sub if teammate hasn't created one yet
            sub_id = db.insert("subscriptions", {
                "number": db.next_sub_number(),
                "customer_email": "client@brightloop.com",
                "plan_id": 1,
                "payment_terms": "15 Days",
                "next_billing_date": today_str,
                "status": "Active"
            })
            st.success(f"Created test sub SUB-{sub_id}!")
            st.rerun()

    st.divider()
    
    if st.button("🚀 Run Billing Day Engine"):
        if not due_subs:
            st.warning("No subscriptions are due for billing today.")
        else:
            created_count = 0
            for sub in due_subs:
                sub_id = sub['id']
                email = sub['customer_email']
                base_amt = sub.get('amount', 1000.0)
                tax_amt = round(base_amt * 0.18, 2)
                total_amt = base_amt + tax_amt
                
                try:
                    db.insert("invoices", {
                        "subscription_id": sub_id,
                        "customer_email": email,
                        "base_amount": base_amt,
                        "tax_amount": tax_amt,
                        "discount_amount": 0.0,
                        "total_amount": total_amt,
                        "status": "Draft",
                        "due_date": today_str,
                        "period_start": today_str
                    })
                    created_count += 1
                except Exception as e:
                    pass

            st.success(f"Billing Day finished! Generated {created_count} draft invoice(s).")
            st.rerun()
            
    st.divider()
    st.subheader("Invoices Ledger")
    invoices = db.list_all("invoices")
    if invoices:
        st.dataframe(invoices, use_container_width=True)
    else:
        st.info("No invoices generated yet.")

# ==========================================
# TAB 3: RECORD PAYMENTS
# ==========================================
with tab3:
    st.subheader("💵 Record Customer Payments")
    st.write("Match received payments against pending invoices.")
    
    unpaid_invoices = db.query("SELECT * FROM invoices WHERE status != 'Paid'")
    
    if unpaid_invoices:
        inv_map = {f"Invoice #{inv['id']} - {inv['customer_email']} (Total: ₹{inv['total_amount']})": inv for inv in unpaid_invoices}
        selected_label = st.selectbox("Select Outstanding Invoice", list(inv_map.keys()))
        selected_inv = inv_map[selected_label]
        
        already_paid = db.get_invoice_paid(selected_inv['id'])
        remaining_balance = selected_inv['total_amount'] - already_paid
        
        st.info(f"Invoice Total: **₹{selected_inv['total_amount']}** | Already Paid: **₹{already_paid}** | Remaining: **₹{remaining_balance}**")
        
        with st.form("record_payment_form"):
            method = st.selectbox("Payment Method", ["UPI", "Credit Card", "Bank Transfer", "Cash"])
            pay_amount = st.number_input("Amount Received (₹)", min_value=1.0, value=float(remaining_balance))
            pay_date = st.date_input("Payment Date", date.today())
            note = st.text_input("Transaction Ref / Note", placeholder="e.g. TXN123456")
            
            submit_pay = st.form_submit_button("Submit Payment")
            
            if submit_pay:
                db.record_payment(selected_inv['id'], method, pay_amount, str(pay_date), note)
                st.success(f"Payment of ₹{pay_amount} recorded for Invoice #{selected_inv['id']}!")
                st.rerun()
    else:
        st.success("All invoices are currently fully paid!")

# ==========================================
# TAB 4: FINANCE LEAD DASHBOARD
# ==========================================
with tab4:
    st.subheader("📈 Executive Finance Dashboard")
    st.write("Real-time revenue, subscription counts, and overdue receivables.")
    
    kpis = db.get_kpis()
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Active Subscriptions", kpis.get('active_subs', 0))
    col2.metric("Total Revenue", f"₹{kpis.get('revenue', 0.0):,.2f}")
    col3.metric("Outstanding Balance", f"₹{kpis.get('outstanding', 0.0):,.2f}")
    col4.metric("Overdue Count", kpis.get('overdue_count', 0), delta="-Action Required", delta_color="inverse")
    
    st.divider()
    
    st.subheader("⚠️ Overdue Invoices Tracker")
    overdue_invoices = db.get_overdue_invoices()
    if overdue_invoices:
        st.dataframe(overdue_invoices, use_container_width=True)
    else:
        st.success("Great news! There are no overdue invoices at this time.")