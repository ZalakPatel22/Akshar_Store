import re
from datetime import datetime, timezone
from functools import wraps

from flask import jsonify, request, session
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from models import Customer, db


def register_customer_auth(app, limiter):
    """Register customer-only auth endpoints; the admin auth routes remain separate."""

    def json_error(message, status):
        return jsonify(error=message), status

    def customer_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            customer_id = session.get("customer_id")
            if not customer_id or session.get("admin_id"):
                return json_error("Customer authentication required", 401)
            if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-CSRF-Token") != session.get("csrf_token"):
                return json_error("CSRF token missing or invalid", 403)
            return fn(*args, **kwargs)
        return wrapped

    @app.post("/api/customer/auth/register")
    @limiter.limit("5 per minute")
    def customer_register():
        data = request.get_json(silent=True) or {}
        name = str(data.get("full_name", "")).strip()
        username = str(data.get("username", "")).strip()
        email = str(data.get("email", "")).strip().lower()
        phone = re.sub(r"\D", "", str(data.get("mobile", "")))
        password = str(data.get("password", ""))
        confirm = str(data.get("confirm_password", ""))

        if len(name) < 2 or len(name) > 160:
            return json_error("Full name must be between 2 and 160 characters.", 400)
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{2,79}", username):
            return json_error("Username must be 3–80 characters and use letters, numbers, dot, dash or underscore.", 400)
        if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            return json_error("Enter a valid email address.", 400)
        if not 10 <= len(phone) <= 15:
            return json_error("Enter a valid mobile number with 10–15 digits.", 400)
        if not 8 <= len(password) <= 128:
            return json_error("Password must be between 8 and 128 characters.", 400)
        if password != confirm:
            return json_error("Passwords do not match.", 400)

        if Customer.query.filter(Customer.username.isnot(None), Customer.username.ilike(username)).first():
            return json_error("That username is already in use.", 409)
        # Only account holders reserve emails. Legacy guest-checkout rows may have reused email addresses.
        if Customer.query.filter(Customer.password_hash.isnot(None), Customer.email.ilike(email)).first():
            return json_error("An account with that email already exists.", 409)

        # Upgrade an existing guest-checkout customer with the same mobile number so order history stays linked.
        customer = Customer.query.filter_by(phone=phone).order_by(Customer.id.asc()).first()
        if customer and customer.password_hash:
            return json_error("An account with that mobile number already exists.", 409)
        email_owner = Customer.query.filter(Customer.password_hash.isnot(None), Customer.email.ilike(email)).first()
        if email_owner and (not customer or email_owner.id != customer.id):
            return json_error("An account with that email already exists.", 409)

        if customer is None:
            customer = Customer(name=name, phone=phone, email=email, address="")
            db.session.add(customer)
        else:
            customer.name = name
            customer.email = email
        customer.username = username
        customer.password_hash = generate_password_hash(password)
        customer.created_at = customer.created_at or datetime.now(timezone.utc)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return json_error("An account with that username already exists.", 409)
        return jsonify(message="Account created. You can now sign in.", username=customer.username), 201

    @app.post("/api/customer/auth/login")
    @limiter.limit("5 per minute")
    def customer_login():
        data = request.get_json(silent=True) or {}
        identifier = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))
        if not identifier or not password:
            return json_error("Username/email and password are required.", 400)
        customer = Customer.query.filter(
            Customer.password_hash.isnot(None),
            or_(Customer.username.ilike(identifier), Customer.email.ilike(identifier.lower())),
        ).first()
        if not customer or not check_password_hash(customer.password_hash, password):
            return json_error("Invalid username/email or password.", 401)
        session.clear()
        session["customer_id"] = customer.id
        session["csrf_token"] = __import__("secrets").token_urlsafe(24)
        return jsonify(
            message="Login successful.",
            customer={"id": customer.id, "name": customer.name, "username": customer.username,
                      "email": customer.email, "mobile": customer.phone},
            csrf_token=session["csrf_token"],
        )

    @app.get("/api/customer/auth/me")
    @customer_required
    def customer_me():
        customer = db.session.get(Customer, session["customer_id"])
        if customer is None:
            session.clear()
            return json_error("Customer account not found.", 401)
        return jsonify(customer={"id": customer.id, "name": customer.name, "username": customer.username,
                                "email": customer.email, "mobile": customer.phone},
                       csrf_token=session.get("csrf_token"))

    @app.post("/api/customer/auth/logout")
    @customer_required
    def customer_logout():
        session.clear()
        return jsonify(message="Logged out.")
