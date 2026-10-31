
"""seed.py - fills database.db with demo data. Safe to re-run (wipes and reseeds).
Run:  python seed.py
Logins:  admin@brightloop.com / Admin@12345
         staff1@brightloop.com / Staff@12345
         customer1@mail.com .. customer12@mail.com / Customer@123
"""
import random
import time
from datetime import date, timedelta

import db

random.seed(42)
TODAY = date.today()


def d(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


def add(days, iso):
    return (date.fromisoformat(iso) + timedelta(days=days)).isoformat()


PERIOD_DAYS = {"Daily": 1, "Weekly": 7, "Monthly": 30, "Yearly": 365}
TABLES = ["payments", "invoice_lines", "invoices", "subscription_lines", "subscriptions",
          "quotation_template_lines", "quotation_templates", "discounts", "plans", "taxes",
          "product_variants", "products", "password_resets", "users"]


def clear(c):
    for t in TABLES:
        c.execute(f"DELETE FROM {t}")
    c.execute("DELETE FROM sqlite_sequence")


def ins(c, table, data):
    cols = ",".join(data)
    qs = ",".join("?" * len(data))
    return c.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", tuple(data.values())).lastrowid


def seed():
    t0 = time.time()
    db.init_db()
    conn = db.get_conn()
    c = conn

    clear(c)

    # ---------- users (hash once per password to stay fast) ----------
    h_admin, h_staff, h_cust = (db.hash_password(p) for p in
                                ("Admin@12345", "Staff@12345", "Customer@123"))
    ins(c, "users", {"email": "admin@brightloop.com", "password": h_admin, "role": "Admin"})
    for i in (1, 2):
        ins(c, "users", {"email": f"staff{i}@brightloop.com", "password": h_staff, "role": "Staff"})
    customers = [f"customer{i}@mail.com" for i in range(1, 13)]
    for e in customers:
        ins(c, "users", {"email": e, "password": h_cust, "role": "Customer"})

    # ---------- taxes ----------
    tax_ids = {}
    for name, rate in [("GST 5%", 5), ("GST 12%", 12), ("GST 18%", 18)]:
        tax_ids[rate] = ins(c, "taxes", {"name": name, "rate": rate})
    tax_rate = {v: k for k, v in tax_ids.items()}

    # ---------- products + variants ----------
    products = [
        ("CRM Suite", "Software", 1000, 400, "Sales pipeline tool"),
        ("Accounting Pro", "Software", 1500, 600, "Invoicing and books"),
        ("HR Manager", "Software", 800, 300, "Payroll and leave"),
        ("Cloud Storage 1TB", "Add-on", 300, 120, "Extra storage"),
        ("Priority Support", "Add-on", 250, 80, "24x7 support"),
        ("Analytics Pack", "Add-on", 500, 200, "Reports and dashboards"),
    ]
    variant_defs = {
        0: [("Brand", "Odoo", 560), ("Brand", "Zoho", 300), ("Brand", "Custom", 0)],
        1: [("Brand", "Odoo", 560), ("Brand", "Tally", 200)],
        2: [("Edition", "Standard", 0), ("Edition", "Premium", 400)],
        5: [("Brand", "Odoo", 560), ("Brand", "Metabase", 150)],
    }
    prod = {}
    variants = {}
    for i, (n, t, bp, cp, notes) in enumerate(products):
        pid = ins(c, "products", {"name": n, "type": t, "base_price": bp,
                                  "cost_price": cp, "notes": notes})
        prod[pid] = {"name": n, "base": bp}
        variants[pid] = []
        for attr, val, extra in variant_defs.get(i, []):
            vid = ins(c, "product_variants", {"product_id": pid, "attribute": attr,
                                              "value": val, "extra_price": extra})
            variants[pid].append((vid, extra))
    pids = list(prod)

    # ---------- plans ----------
    plan_defs = [
        ("Starter Monthly", 1200, "Monthly", 1, 0, 1, 1, 1),
        ("Pro Monthly", 2500, "Monthly", 2, 0, 1, 1, 1),
        ("Business Yearly", 14000, "Yearly", 5, 1, 0, 1, 1),
        ("Enterprise Yearly", 52000, "Yearly", 10, 1, 0, 1, 0),
        ("Weekly Trial", 300, "Weekly", 1, 1, 0, 0, 1),
        ("Daily Pass", 50, "Daily", 1, 1, 0, 0, 0),
    ]
    plans = {}
    for n, price, per, mq, ac, ap, ar, aec in plan_defs:
        pid = ins(c, "plans", {"name": n, "price": price, "billing_period": per, "min_qty": mq,
                               "start_date": d(-365), "end_date": d(365), "auto_close": ac,
                               "allow_pause": ap, "allow_renew": ar, "allow_early_close": aec})
        plans[pid] = {"period": per, "min_qty": mq}
    plan_ids = list(plans)

    # ---------- quotation templates ----------
    for name, plan_idx, validity, lines in [
        ("Standard SMB Quote", 1, 30, [(0, 2), (3, 1)]),
        ("Enterprise Quote", 3, 60, [(1, 10), (4, 10), (5, 5)]),
    ]:
        tid = ins(c, "quotation_templates", {"name": name, "plan_id": plan_ids[plan_idx],
                                             "validity_days": validity})
        for p_idx, qty in lines:
            ins(c, "quotation_template_lines", {"template_id": tid, "product_id": pids[p_idx],
                                                "qty": qty})

    # ---------- discounts ----------
    for code, typ, val, mq, ma, sd, ed, lim, used, pidx in [
        ("BULK10", "Percentage", 10, 5, 0, d(-60), d(120), 50, 3, None),
        ("WELCOME500", "Fixed", 500, 1, 2000, d(-30), d(60), 100, 12, None),
        ("CRM15", "Percentage", 15, 2, 0, d(-90), d(90), 20, 20, 0),   # exhausted
        ("OLDPROMO", "Fixed", 200, 1, 0, d(-200), d(-20), 30, 5, 3),   # expired
    ]:
        ins(c, "discounts", {"code": code, "type": typ, "value": val, "min_qty": mq,
                             "min_amount": ma, "start_date": sd, "end_date": ed,
                             "usage_limit": lim, "times_used": used,
                             "product_id": pids[pidx] if pidx is not None else None,
                             "active": 1})

    # ---------- subscriptions (20) ----------
    statuses = (["Draft"] * 3 + ["Quotation"] * 3 + ["Confirmed"] * 3 +
                ["Active"] * 8 + ["Closed"] * 3)
    terms = ["Net 15", "Net 30", "Due on receipt"]
    subs = []
    for i, status in enumerate(statuses, start=1):
        plan = random.choice(plan_ids)
        per = plans[plan]["period"]
        if status == "Active":
            start = d(-random.randint(40, 150))
        elif status == "Closed":
            start = d(-random.randint(250, 400))
        elif status == "Confirmed":
            start = d(random.randint(1, 10))
        else:
            start = d(random.randint(5, 30))
        expiry = add(365 if per == "Yearly" else 180, start)
        if status == "Closed":
            expiry = d(-random.randint(5, 60))

        sid = ins(c, "subscriptions", {
            "number": f"SUB-{i:04d}", "customer_email": customers[(i - 1) % len(customers)],
            "plan_id": plan, "status": status, "start_date": start, "expiry_date": expiry,
            "payment_terms": random.choice(terms), "total_amount": 0,
            "next_billing_date": start})

        lines, total = [], 0
        for pid in random.sample(pids, random.randint(1, 3)):
            vid, extra = (random.choice(variants[pid]) if variants[pid] and random.random() < .6
                          else (None, 0))
            unit = prod[pid]["base"] + extra
            mq = max(1, plans[plan]["min_qty"])
            qty = random.randint(mq, mq + 4)
            amount = unit * qty
            tid = random.choice(list(tax_ids.values()))
            ins(c, "subscription_lines", {"subscription_id": sid, "product_id": pid,
                                          "variant_id": vid, "qty": qty, "unit_price": unit,
                                          "tax_id": tid, "amount": amount})
            lines.append((pid, qty, unit, amount, round(amount * tax_rate[tid] / 100, 2)))
            total += amount
        c.execute("UPDATE subscriptions SET total_amount=? WHERE id=?", (total, sid))
        subs.append(dict(id=sid, status=status, email=customers[(i - 1) % len(customers)],
                         start=start, per=per, lines=lines, total=total))

    # ---------- invoices + payments ----------
    n_inv = n_pay = 0
    active_idx = 0
    for s in subs:
        if s["status"] not in ("Active", "Closed"):
            continue
        step = PERIOD_DAYS[s["per"]]
        if s["per"] in ("Daily", "Weekly"):
            step = 30  # keep invoice count small for demo
        starts, p = [], s["start"]
        while p <= d(0):
            starts.append(p)
            p = add(step, p)
        starts = starts[-3:]
        for k, ps in enumerate(starts):
            last = k == len(starts) - 1
            if s["status"] == "Closed":
                status = "Paid"
            elif last:
                status = ["Paid", "Confirmed", "Confirmed", "Draft"][active_idx % 4]
            else:
                status = "Confirmed" if (active_idx % 3 == 0 and k == len(starts) - 2) else "Paid"

            base = s["total"]
            tax = round(sum(l[4] for l in s["lines"]), 2)
            disc = round(base * 0.10, 2) if active_idx % 5 == 0 else 0
            total = round(base + tax - disc, 2)
            iid = ins(c, "invoices", {
                "subscription_id": s["id"], "customer_email": s["email"],
                "base_amount": base, "tax_amount": tax, "discount_amount": disc,
                "total_amount": total, "status": status, "due_date": add(15, ps),
                "period_start": ps})
            n_inv += 1
            for pid, qty, unit, amount, tx in s["lines"]:
                ins(c, "invoice_lines", {"invoice_id": iid, "product_id": pid,
                                         "description": prod[pid]["name"], "qty": qty,
                                         "unit_price": unit, "tax_amount": tx, "amount": amount})
            if status == "Paid":
                ins(c, "payments", {"invoice_id": iid,
                                    "method": random.choice(["UPI", "Card", "Bank Transfer"]),
                                    "amount": total, "payment_date": add(random.randint(1, 10), ps),
                                    "note": "Paid in full"})
                n_pay += 1
            elif status == "Confirmed" and active_idx % 5 == 1:
                ins(c, "payments", {"invoice_id": iid, "method": "UPI",
                                    "amount": round(total * 0.4, 2),
                                    "payment_date": add(5, ps), "note": "Partial payment"})
                n_pay += 1
        if s["status"] == "Active":
            # even-numbered active subs are DUE today so billing day has work to do
            nxt = d(0) if active_idx % 2 == 0 else add(step, starts[-1])
            c.execute("UPDATE subscriptions SET next_billing_date=? WHERE id=?", (nxt, s["id"]))
            active_idx += 1

    conn.commit()
    conn.close()

    # ---------- summary ----------
    print(f"Seeded in {time.time() - t0:.2f}s")
    for t in TABLES[::-1]:
        print(f"  {t:26s}{db.query_one(f'SELECT COUNT(*) n FROM {t}')['n']}")
    print("KPIs:", db.get_kpis())
    print("Admin login: admin@brightloop.com / Admin@12345")


if __name__ == "__main__":
    seed()