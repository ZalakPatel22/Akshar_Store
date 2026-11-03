import os
import re
import secrets
from decimal import Decimal, InvalidOperation
from pathlib import Path
from functools import wraps
from io import BytesIO

from flask import Flask, jsonify, request, session, send_file
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from werkzeug.security import check_password_hash, generate_password_hash
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import event
from sqlalchemy.engine import Engine

from config import Config
from models import db, Admin, Category, Product, Customer, Order, OrderItem, InventoryMovement, Payment

@event.listens_for(Engine, "connect")
def sqlite_foreign_keys(connection, _):
    if connection.__class__.__module__ == "sqlite3":
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.instance_path, exist_ok=True)
    db.init_app(app)
    Migrate(app, db)
    CORS(app, origins=[app.config["FRONTEND_ORIGIN"]], supports_credentials=True)
    limiter = Limiter(get_remote_address, app=app, default_limits=[])

    @app.after_request
    def csrf_cookie(response):
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(24)
        response.headers["X-CSRF-Token"] = session["csrf_token"]
        return response

    def admin_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get("admin_id"):
                return jsonify(error="Authentication required"), 401
            if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-CSRF-Token") != session.get("csrf_token"):
                return jsonify(error="CSRF token missing or invalid"), 403
            return fn(*args, **kwargs)
        return wrapped

    def json_error(message, status):
        return jsonify(error=message), status

    def money(value):
        try:
            amount = Decimal(str(value))
            if not amount.is_finite() or amount < 0:
                raise InvalidOperation
            return amount.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("Money values must be non-negative decimal amounts")

    def product_json(p):
        return {"id": p.id, "name": p.name, "slug": p.slug, "sku": p.sku, "description": p.description,
                "price": str(p.price), "stock": p.stock, "category": p.category.name if p.category else None,
                "category_id": p.category_id, "active": p.active}

    @app.cli.command("init-db")
    def init_db():
        """Create tables without deleting existing data; use Flask-Migrate for schema changes."""
        db.create_all()
        print("Database tables are ready.")

    @app.cli.command("create-admin")
    def create_admin():
        """Create the single initial admin from AKSHAR_ADMIN_USERNAME/PASSWORD environment variables."""
        from flask import current_app
        username = os.getenv("AKSHAR_ADMIN_USERNAME", "").strip()
        password = os.getenv("AKSHAR_ADMIN_PASSWORD", "")
        if not username or len(password) < 12:
            raise SystemExit("Set AKSHAR_ADMIN_USERNAME and a 12+ character AKSHAR_ADMIN_PASSWORD first.")
        if Admin.query.first():
            raise SystemExit("An admin already exists; public registration is disabled.")
        db.session.add(Admin(username=username, password_hash=generate_password_hash(password)))
        db.session.commit()
        print("Admin created.")

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", service="akshar-store")

    @app.get("/api/auth/csrf")
    def csrf():
        return jsonify(csrf_token=session.get("csrf_token"))

    @app.post("/api/auth/login")
    @limiter.limit("5 per minute")
    def login():
        data = request.get_json(silent=True) or {}
        admin = Admin.query.filter_by(username=str(data.get("username", "")).strip()).first()
        if not admin or not check_password_hash(admin.password_hash, str(data.get("password", ""))):
            return json_error("Invalid username or password", 401)
        session.clear()
        session["admin_id"] = admin.id
        session["csrf_token"] = secrets.token_urlsafe(24)
        return jsonify(username=admin.username, csrf_token=session["csrf_token"])

    @app.post("/api/auth/logout")
    @admin_required
    def logout():
        session.clear()
        return jsonify(message="Logged out")

    @app.get("/api/auth/me")
    @admin_required
    def me():
        admin = db.session.get(Admin, session["admin_id"])
        return jsonify(username=admin.username, csrf_token=session.get("csrf_token"))

    @app.get("/api/products")
    def products_list():
        query = Product.query.filter_by(active=True)
        if request.args.get("category"):
            query = query.join(Category).filter(Category.slug == request.args["category"])
        if request.args.get("q"):
            term = "%" + request.args["q"].strip()[:80] + "%"
            query = query.filter(Product.name.ilike(term))
        return jsonify(products=[product_json(p) for p in query.order_by(Product.created_at.desc()).all()])

    @app.get("/api/categories")
    def categories_list():
        return jsonify(categories=[{"id": c.id, "name": c.name, "slug": c.slug} for c in Category.query.filter_by(active=True).order_by(Category.name).all()])

    @app.post("/api/admin/categories")
    @admin_required
    def category_create():
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not name or not slug:
            return json_error("Category name is required", 400)
        if Category.query.filter((Category.name == name) | (Category.slug == slug)).first():
            return json_error("Category already exists", 409)
        category = Category(name=name, slug=slug, description=str(data.get("description", ""))[:2000])
        db.session.add(category)
        db.session.commit()
        return jsonify(id=category.id, name=category.name, slug=category.slug), 201

    @app.route("/api/admin/products", methods=["GET", "POST"])
    @admin_required
    def admin_products():
        if request.method == "GET":
            return jsonify(products=[product_json(p) for p in Product.query.order_by(Product.id.desc()).all()])
        data = request.get_json(silent=True) or {}
        try:
            name, sku = str(data.get("name", "")).strip(), str(data.get("sku", "")).strip()
            price, purchase = money(data.get("price")), money(data.get("purchase_price", 0))
            stock = int(data.get("stock", 0))
            if not name or not sku or stock < 0 or len(name) > 180 or len(sku) > 80:
                return json_error("Valid name, SKU, price, and non-negative stock are required", 400)
            if Product.query.filter((Product.sku == sku) | (Product.slug == re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"))).first():
                return json_error("Product SKU or name slug already exists", 409)
            category_id = data.get("category_id") or None
            if category_id and not db.session.get(Category, int(category_id)):
                return json_error("Category not found", 400)
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            p = Product(name=name, slug=slug, sku=sku, description=str(data.get("description", ""))[:5000],
                        price=price, purchase_price=purchase, stock=stock, category_id=category_id)
            db.session.add(p)
            db.session.flush()
            if stock:
                db.session.add(InventoryMovement(product_id=p.id, movement_type="initial", quantity=stock, previous_stock=0, new_stock=stock, reason="Initial stock"))
            db.session.commit()
            return jsonify(product=product_json(p)), 201
        except (ValueError, InvalidOperation, TypeError):
            db.session.rollback()
            return json_error("Invalid product data", 400)

    @app.route("/api/admin/products/<int:product_id>", methods=["PUT", "DELETE"])
    @admin_required
    def product_detail(product_id):
        p = db.session.get(Product, product_id)
        if not p:
            return json_error("Product not found", 404)
        if request.method == "DELETE":
            if OrderItem.query.filter_by(product_id=p.id).first():
                p.active = False
                db.session.commit()
                return jsonify(message="Product archived because it appears in order history")
            db.session.delete(p)
            db.session.commit()
            return jsonify(message="Product deleted")
        data = request.get_json(silent=True) or {}
        try:
            if "name" in data:
                name = str(data["name"]).strip()
                if not name:
                    return json_error("Name cannot be empty", 400)
                p.name = name
            if "price" in data: p.price = money(data["price"])
            if "purchase_price" in data: p.purchase_price = money(data["purchase_price"])
            if "description" in data: p.description = str(data["description"])[:5000]
            if "active" in data: p.active = bool(data["active"])
            db.session.commit()
            return jsonify(product=product_json(p))
        except (ValueError, InvalidOperation, TypeError):
            db.session.rollback()
            return json_error("Invalid product data", 400)

    @app.post("/api/orders")
    @limiter.limit("10 per minute")
    def place_order():
        data = request.get_json(silent=True) or {}
        name, phone = str(data.get("name", "")).strip(), re.sub(r"\D", "", str(data.get("phone", "")))
        lines = data.get("items")
        if not name or len(phone) < 10 or len(phone) > 15 or not isinstance(lines, list) or not lines or len(lines) > 50:
            return json_error("Valid customer details and order items are required", 400)
        try:
            # Locking/transaction boundaries are essential for stock correctness; SQLite serializes writers.
            items, total = [], Decimal("0.00")
            for line in lines:
                p = db.session.get(Product, int(line.get("product_id", 0)))
                qty = int(line.get("quantity", 0))
                if not p or not p.active or qty < 1 or qty > 100 or p.stock < qty:
                    db.session.rollback()
                    return json_error("An item is unavailable or has insufficient stock", 409)
                line_total = Decimal(p.price) * qty
                items.append((p, qty, line_total))
                total += line_total
            customer = Customer.query.filter_by(phone=phone).first()
            if customer is None:
                customer = Customer(name=name, phone=phone, email=str(data.get("email", ""))[:254] or None,
                                    address=str(data.get("address", ""))[:1500])
                db.session.add(customer)
                db.session.flush()
            else:
                customer.name = name
                customer.email = str(data.get("email", ""))[:254] or customer.email
            order = Order(order_number="AS" + secrets.token_hex(5).upper(), customer=customer, source="online",
                          status="New", payment_method="Cash on Delivery", subtotal=total, grand_total=total)
            db.session.add(order)
            db.session.flush()
            for p, qty, line_total in items:
                before = p.stock
                p.stock -= qty
                db.session.add(OrderItem(order_id=order.id, product_id=p.id, product_name=p.name, sku=p.sku,
                                         quantity=qty, unit_price=p.price, line_total=line_total))
                db.session.add(InventoryMovement(product_id=p.id, movement_type="sale", quantity=qty,
                    previous_stock=before, new_stock=p.stock, reason="Online order", order_id=order.id))
            db.session.commit()
            return jsonify(order_number=order.order_number, status=order.status, grand_total=str(order.grand_total)), 201
        except (ValueError, TypeError, InvalidOperation):
            db.session.rollback()
            return json_error("Invalid order data", 400)

    @app.get("/api/admin/orders")
    @admin_required
    def orders_list():
        orders = Order.query.order_by(Order.created_at.desc()).limit(500).all()
        return jsonify(orders=[{"id": o.id, "order_number": o.order_number, "customer": o.customer.name if o.customer else "Walk-in",
            "phone": o.customer.phone if o.customer else "", "source": o.source, "status": o.status,
            "payment_status": o.payment_status, "total": str(o.grand_total), "created_at": o.created_at.isoformat(),
            "items": [{"name": i.product_name, "sku": i.sku, "quantity": i.quantity, "line_total": str(i.line_total)} for i in o.items]} for o in orders])

    @app.post("/api/admin/orders/<int:order_id>/status")
    @admin_required
    def order_status(order_id):
        o = db.session.get(Order, order_id)
        status = str((request.get_json(silent=True) or {}).get("status", ""))
        allowed = {"New", "Confirmed", "Processing", "Packed", "Shipped", "Delivered", "Cancelled"}
        if not o or status not in allowed:
            return json_error("Order or status is invalid", 400)
        if status == "Cancelled" and o.status != "Cancelled" and o.stock_deducted:
            for item in o.items:
                if item.product_id:
                    p = db.session.get(Product, item.product_id)
                    before = p.stock
                    p.stock += item.quantity
                    db.session.add(InventoryMovement(product_id=p.id, movement_type="return", quantity=item.quantity,
                        previous_stock=before, new_stock=p.stock, reason="Order cancellation", order_id=o.id))
            o.stock_deducted = False
        o.status = status
        db.session.commit()
        return jsonify(message="Order status updated", status=o.status)

    @app.post("/api/admin/orders/<int:order_id>/payments")
    @admin_required
    def add_payment(order_id):
        o = db.session.get(Order, order_id)
        if not o: return json_error("Order not found", 404)
        data = request.get_json(silent=True) or {}
        try:
            amount, method = money(data.get("amount")), str(data.get("method", ""))
            if amount <= 0 or method not in {"Cash", "UPI", "Bank Transfer", "Card", "Cash on Delivery", "Other"}:
                return json_error("Valid positive payment and method are required", 400)
            due = Decimal(o.grand_total) - Decimal(o.amount_paid)
            if amount > due: return json_error("Payment exceeds the outstanding balance", 400)
            payment = Payment(order_id=o.id, amount=amount, method=method, reference=str(data.get("reference", ""))[:120])
            o.amount_paid = Decimal(o.amount_paid) + amount
            o.payment_status = "Paid" if o.amount_paid >= o.grand_total else "Partially Paid"
            db.session.add(payment)
            db.session.commit()
            return jsonify(payment_status=o.payment_status, amount_paid=str(o.amount_paid)), 201
        except (ValueError, TypeError, InvalidOperation):
            db.session.rollback()
            return json_error("Invalid payment data", 400)

    @app.get("/api/admin/orders/<int:order_id>/invoice")
    @admin_required
    def invoice(order_id):
        o = db.session.get(Order, order_id)
        if not o: return json_error("Order not found", 404)
        output = BytesIO()
        pdf = canvas.Canvas(output, pagesize=A4)
        width, height = A4
        pdf.setFillColorRGB(.29, .21, .16)
        pdf.setFont("Helvetica-Bold", 22)
        pdf.drawCentredString(width / 2, height - 50, "AKSHAR STORE")
        pdf.setFont("Helvetica", 10)
        pdf.drawCentredString(width / 2, height - 68, "Contact: 9979494032, 8866912212")
        pdf.setStrokeColorRGB(.72, .60, .40)
        pdf.line(45, height - 82, width - 45, height - 82)
        pdf.setFillColorRGB(.15, .12, .10)
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(45, height - 110, "INVOICE")
        pdf.setFont("Helvetica", 10)
        y = height - 132
        for text in [f"Invoice / Order: {o.order_number}", f"Date: {o.created_at.strftime('%d-%m-%Y')}",
                     f"Customer: {o.customer.name if o.customer else 'Walk-in'}", f"Mobile: {o.customer.phone if o.customer else ''}",
                     f"Address: {o.customer.address if o.customer else ''}", "", "Item | SKU | Qty | Unit Price | Total"]:
            pdf.drawString(45, y, text[:110]); y -= 18
        for item in o.items:
            pdf.drawString(45, y, f"{item.product_name[:28]} | {item.sku[:14]} | {item.quantity} | INR {item.unit_price} | INR {item.line_total}")
            y -= 17
            if y < 100:
                pdf.showPage(); y = height - 50; pdf.setFont("Helvetica", 10)
        pdf.setFont("Helvetica-Bold", 11)
        for text in [f"Total: INR {o.grand_total}", f"Paid: INR {o.amount_paid}", f"Balance: INR {Decimal(o.grand_total)-Decimal(o.amount_paid)}", f"Payment status: {o.payment_status}"]:
            y -= 20; pdf.drawString(45, y, text)
        pdf.setFont("Helvetica-Oblique", 10)
        pdf.drawCentredString(width / 2, 45, "Thank You for Shopping with Akshar Store!")
        pdf.save(); output.seek(0)
        return send_file(output, mimetype="application/pdf", as_attachment=True, download_name=f"{o.order_number}.pdf")

    @app.get("/api/orders/track")
    @limiter.limit("10 per minute")
    def track_order():
        number = str(request.args.get("order_number", ""))[:32]
        phone = re.sub(r"\D", "", str(request.args.get("phone", "")))
        o = Order.query.filter_by(order_number=number).first()
        if not o or not o.customer or not secrets.compare_digest(o.customer.phone, phone):
            return json_error("Order not found. Check the order number and mobile number.", 404)
        return jsonify(order_number=o.order_number, status=o.status, payment_status=o.payment_status,
                       items=[{"name": i.product_name, "quantity": i.quantity} for i in o.items])

    return app

app = create_app()
