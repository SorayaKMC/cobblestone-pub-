"""Cobblestone Pub Management App."""

from functools import wraps
from flask import Flask, redirect, url_for, request, Response
from datetime import date
import os
import secrets
import db
import config


def check_auth(username, password):
    """Constant-time comparison of provided creds against configured ones."""
    if not config.AUTH_ENABLED:
        return True
    return (
        secrets.compare_digest(username or "", config.AUTH_USERNAME)
        and secrets.compare_digest(password or "", config.AUTH_PASSWORD)
    )


def require_auth(f):
    """Decorator to protect routes with HTTP Basic Auth."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not config.AUTH_ENABLED:
            return f(*args, **kwargs)
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                "Authentication required.",
                401,
                {"WWW-Authenticate": 'Basic realm="Cobblestone Pub Manager"'},
            )
        return f(*args, **kwargs)
    return wrapper


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "cobblestone-pub-local-app-2026")

    @app.context_processor
    def inject_globals():
        return {"today": date.today().strftime("%A, %d %B %Y")}

    # Initialize database
    with app.app_context():
        db.init_db()

    # Apply HTTP Basic Auth globally (if enabled via env vars)
    if config.AUTH_ENABLED:
        @app.before_request
        def protect_all():
            # Allow static files and health checks without auth
            if request.endpoint in ("static", "healthz"):
                return None
            auth = request.authorization
            if not auth or not check_auth(auth.username, auth.password):
                return Response(
                    "Please log in to access the Cobblestone Pub Manager.",
                    401,
                    {"WWW-Authenticate": 'Basic realm="Cobblestone Pub Manager"'},
                )

    # Register blueprints
    from routes import settings, payroll, dashboard, pto
    app.register_blueprint(settings.bp)
    app.register_blueprint(payroll.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(pto.bp)

    @app.route("/")
    def index():
        return redirect(url_for("dashboard.dashboard_page"))

    @app.route("/healthz")
    def healthz():
        return "ok", 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, port=port)
