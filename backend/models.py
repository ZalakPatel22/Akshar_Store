from datetime import datetime, timezone
from decimal import Decimal
from flask_sqlalchemy import SQLAlchemy

 db = SQLAlchemy()

 def utcnow():
     return datetime.now(timezone.utc)

 class Admin(db.Model):
     id = db.Column(db.Integer, primary_key=True)
     username = db.Column(db.String(80), unique=True, nullable=False)
     password_hash = db.Column(db.String(255), nullable=False)

 class Category(db.Model):
     id = db.Column(db.Integer, primary_key=True)
     name = db.Column(db.String(120), unique=True, nullable=False)
     slug = db.Column(db.String(140), unique=True, nullable=False)
     description = db.Column(db.Text, default="")
     active = db.Column(db.Boolean, default=True, nullable=False)

 class Product(db.Model):
     id = db.Column(db.Integer, primary_key=True)
     name = db.Column(db.String(180), nullable=False)
     slug = db.Column(db.String(200), unique=True, nullable=False)
     sku = db.Column(db.String(80), unique=True, nullable=False)
     description = db.Column(db.Text, default="")
     price = db.Column(db.Numeric(12, 2), nullable=False)
     purchase_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
     stock = db.Column(db.Integer, nullable=False, default=0)
     active = db.Column(db.Boolean, nullable=False, default=True)
     category_id = db.Column(db.Integer, db.ForeignKey("category.id", ondelete="SET NULL"))
     category = db.relationship("Category")
     created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

 class Customer(db.Model):
     id = db.Column(db.Integer, primary_key=True)
     name = db.Column(db.String(160), nullable=False)
     phone = db.Column(db.String(20), nullable=False, index=True)
     email = db.Column(db.String(254))
     address = db.Column(db.Text, default="")
     # Nullable to preserve guest-checkout customers already in the database.
     username = db.Column(db.String(80), unique=True, index=True, nullable=True)
     password_hash = db.Column(db.String(255), nullable=True)
     created_at = db.Column(db.DateTime(timezone=True), nullable=True, default=utcnow)

 class Order(db.Model):
     id = db.Column(db.Integer, primary_key=True)
     order_number = db.Column(db.String(32), unique=True, nullable=False, index=True)
     customer_id = db.Column(db.Integer, db.ForeignKey("customer.id", ondelete="SET NULL"))
     customer = db.relationship("Customer")
     source = db.Column(db.String(12), nullable=False, default="online")
     status = db.Column(db.String(24), nullable=False, default="New")
     payment_status = db.Column(db.String(24), nullable=False, default="Pending")
     payment_method = db.Column(db.String(30), nullable=False, default="Cash on Delivery")
     subtotal = db.Column(db.Numeric(12, 2), nullable=False)
     grand_total = db.Column(db.Numeric(12, 2), nullable=False)
     amount_paid = db.Column(db.Numeric(12, 2), nullable=False, default=0)
     stock_deducted = db.Column(db.Boolean, nullable=False, default=True)
     created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
     items = db.relationship("OrderItem", cascade="all, delete-orphan", lazy=True)

 class OrderItem(db.Model):
     id = db.Column(db.Integer, primary_key=True)
     order_id = db.Column(db.Integer, db.ForeignKey("order.id", ondelete="CASCADE"), nullable=False)
     product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="SET NULL"))
     product_name = db.Column(db.String(180), nullable=False)
     sku = db.Column(db.String(80), nullable=False)
     quantity = db.Column(db.Integer, nullable=False)
     unit_price = db.Column(db.Numeric(12, 2), nullable=False)
     line_total = db.Column(db.Numeric(12, 2), nullable=False)

 class InventoryMovement(db.Model):
     id = db.Column(db.Integer, primary_key=True)
     product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="SET NULL"))
     movement_type = db.Column(db.String(20), nullable=False)
     quantity = db.Column(db.Integer, nullable=False)
     previous_stock = db.Column(db.Integer, nullable=False)
     new_stock = db.Column(db.Integer, nullable=False)
     reason = db.Column(db.String(255), default="")
     order_id = db.Column(db.Integer, db.ForeignKey("order.id", ondelete="SET NULL"))
     created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

 class Payment(db.Model):
     id = db.Column(db.Integer, primary_key=True)
     order_id = db.Column(db.Integer, db.ForeignKey("order.id", ondelete="CASCADE"), nullable=False)
     amount = db.Column(db.Numeric(12, 2), nullable=False)
     method = db.Column(db.String(30), nullable=False)
     reference = db.Column(db.String(120), default="")
     created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
