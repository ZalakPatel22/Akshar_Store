import os
from app import create_app
from models import db, Admin, Category, Product, Order


def test_admin_api_requires_login(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "test-secret", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}", "RATELIMIT_ENABLED": False})
    with app.app_context():
        db.create_all()
        client = app.test_client()
        assert client.get("/api/admin/products").status_code == 401
        db.session.add(Admin(username="owner", password_hash=""))
        db.session.commit()
        db.drop_all()


def test_health(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "test-secret", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'health.db'}", "RATELIMIT_ENABLED": False})
    response = app.test_client().get("/api/health")
    assert response.status_code == 200
    assert response.json["status"] == "ok"
