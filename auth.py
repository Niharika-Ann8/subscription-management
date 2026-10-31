"""auth.py - Login, sign up, password reset and staff management (Streamlit).

Exports: show_auth_page(), show_staff_page(), logout()

Session rule: st.session_state["user"] holds the logged-in user as a dict
{"id", "email", "role"}, or None when nobody is logged in.

All database work goes through the helpers in db.py. Nothing runs at import time.
"""
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import db

MIN_PASSWORD_LENGTH = 9          # "more than 8 characters"
RESET_TOKEN_MINUTES = 30         # how long a reset token stays valid


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _clean_email(email):
    return (email or "").strip().lower()


def _password_errors(password):
    """Return a list of readable messages, one per broken rule (empty = OK)."""
    errors = []
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append("Password must be more than 8 characters (at least 9).")
    if not any(ch.isupper() for ch in password):
        errors.append("Password needs at least 1 uppercase letter.")
    if not any(ch.islower() for ch in password):
        errors.append("Password needs at least 1 lowercase letter.")
    if not any((not ch.isalnum()) and (not ch.isspace()) for ch in password):
        errors.append("Password needs at least 1 special character (for example ! @ # $ %).")
    return errors


def _show_errors(messages):
    for message in messages:
        st.error(message)


# ---------------------------------------------------------------------------
# Auth page (Login / Sign up / Forgot password)
# ---------------------------------------------------------------------------
def _login_tab():
    with st.form("login_form"):
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        submitted = st.form_submit_button("Log in")

    if not submitted:
        return

    email = _clean_email(email)
    if not email or not password:
        st.error("Please enter both your email and your password.")
        return

    user = db.login(email, password)
    if user is None:
        st.error("Wrong email or password.")
        return

    # Keep only what the app needs. Never keep the password hash in the session.
    st.session_state["user"] = {"id": user["id"], "email": user["email"], "role": user["role"]}
    st.rerun()


def _signup_tab():
    with st.form("signup_form"):
        email = st.text_input("Email", key="signup_email")
        password = st.text_input("Password", type="password", key="signup_password")
        confirm = st.text_input("Confirm password", type="password", key="signup_confirm")
        st.caption("At least 9 characters, with 1 uppercase, 1 lowercase and 1 special character.")
        submitted = st.form_submit_button("Create account")

    if not submitted:
        return

    email = _clean_email(email)
    errors = []
    if not email:
        errors.append("Please enter your email.")
    errors.extend(_password_errors(password))
    if password != confirm:
        errors.append("The two passwords do not match.")
    if errors:
        _show_errors(errors)
        return

    # Sign up ALWAYS creates a Customer. Nobody can pick their own role here.
    new_id = db.create_user(email, password, "Customer")
    if new_id is None:
        st.error("An account with this email already exists.")
        return
    st.success("Account created. You can now log in from the Login tab.")


def _forgot_password_tab():
    # Step 1: ask for a token
    st.markdown("**Step 1 - Get a reset token**")
    with st.form("reset_request_form"):
        email = st.text_input("Your account email", key="reset_email")
        requested = st.form_submit_button("Generate reset token")

    if requested:
        email = _clean_email(email)
        if not email or db.get_user(email) is None:
            st.error("No account was found with that email.")
        else:
            expires_at = (datetime.now() + timedelta(minutes=RESET_TOKEN_MINUTES)).isoformat(
                timespec="seconds")
            token = db.create_reset_token(email, expires_at)
            st.session_state["reset_token_info"] = {"email": email, "token": token}

    # This slot is filled AFTER step 2 runs, so the token box disappears
    # right after a successful reset.
    token_slot = st.empty()

    # Step 2: use the token
    st.markdown("**Step 2 - Set a new password**")
    with st.form("reset_apply_form"):
        token_in = st.text_input("Reset token", key="reset_token_input")
        new_pw = st.text_input("New password", type="password", key="reset_new_password")
        applied = st.form_submit_button("Change password")

    if applied:
        _apply_password_reset(token_in.strip(), new_pw)

    info = st.session_state.get("reset_token_info")
    if info:
        with token_slot.container():
            st.info(
                f"Demo mode: there is no email server, so your token for {info['email']} "
                f"is shown here. It is valid for {RESET_TOKEN_MINUTES} minutes."
            )
            st.code(info["token"], language=None)


def _apply_password_reset(token, new_pw):
    if not token:
        st.error("Please enter your reset token.")
        return

    records = db.query("SELECT * FROM password_resets WHERE token=?", (token,))
    if not records:
        st.error("That token is not valid.")
        return
    record = records[0]

    try:
        expired = datetime.fromisoformat(record["expires_at"]) < datetime.now()
    except (TypeError, ValueError):
        expired = True
    if expired:
        st.error("That token has expired. Please generate a new one.")
        return

    errors = _password_errors(new_pw)
    if errors:
        _show_errors(errors)
        return

    user = db.get_user(record["email"])
    if user is None:
        st.error("The account for this token no longer exists.")
        return

    db.update("users", user["id"], {"password": db.hash_password(new_pw)})
    st.session_state.pop("reset_token_info", None)
    st.success("Password changed. You can now log in from the Login tab.")


def show_auth_page():
    """Centered card with Login, Sign up and Forgot password tabs."""
    _, middle, _ = st.columns([1, 2, 1])
    with middle:
        with st.container(border=True):
            st.subheader("Welcome to BrightLoop Subscriptions")
            login_tab, signup_tab, forgot_tab = st.tabs(["Login", "Sign up", "Forgot password"])
            with login_tab:
                _login_tab()
            with signup_tab:
                _signup_tab()
            with forgot_tab:
                _forgot_password_tab()


# ---------------------------------------------------------------------------
# Staff management (Admin only)
# ---------------------------------------------------------------------------
def show_staff_page():
    """Admin-only page: add Staff users and list Admin/Staff users."""
    user = st.session_state.get("user")
    if not user or user.get("role") != "Admin":
        st.error("Only Admins can open this page.")
        st.stop()

    st.title("Staff management")

    st.subheader("Add a staff user")
    with st.form("add_staff_form"):
        email = st.text_input("Staff email", key="staff_email")
        password = st.text_input("Password", type="password", key="staff_password")
        st.caption("At least 9 characters, with 1 uppercase, 1 lowercase and 1 special character.")
        submitted = st.form_submit_button("Add staff user")

    if submitted:
        email = _clean_email(email)
        errors = []
        if not email:
            errors.append("Please enter an email.")
        errors.extend(_password_errors(password))
        if errors:
            _show_errors(errors)
        else:
            new_id = db.create_user(email, password, "Staff")
            if new_id is None:
                st.error("A user with this email already exists.")
            else:
                st.success(f"Staff user {email} was added.")

    # Drawn after the form, so a newly added user shows up straight away.
    st.subheader("Admin and Staff users")
    rows = db.query(
        "SELECT id, email, role FROM users WHERE role IN ('Admin', 'Staff') ORDER BY role, email"
    )
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True)
    else:
        st.info("No Admin or Staff users yet.")


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
def logout():
    """Clear the whole session and reload the app."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.session_state["user"] = None
    st.rerun()