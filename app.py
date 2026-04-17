"""Cobblestone Pub Management App."""

from functools import wraps
from flask import Flask, redirect, url_for, request, Response
from datetime import date
import os
import secrets
import threading
import db
import config


def _warmup_cache():
    """Pre-populate dashboard cache in a background thread at startup.

    Fetches 2 years of weekly data from Square so the /dashboard route
    doesn't time out on first request (Render edge times out at 100s,
    but initial cold fetch takes ~3 min).
    """
    try:
        import time
        time.sleep(5)  # let app finish booting
        from routes.dashboard import _get_week_sales_with_daily, _get_week_payroll
        import square_client

        current_year, current_week = square_client.current_week()
        print(f"[warmup] Starting cache warmup for {current_year} W02-W{current_week}")

        for week in range(2, current_week + 1):
            try:
                _get_week_sales_with_daily(current_year, week)
                _get_week_sales_with_daily(current_year - 1, week)
                _get_week_payroll(current_year, week)
                print(f"[warmup] W{week:02d} cached")
            except Exception as e:
                print(f"[warmup] W{week:02d} failed: {e}")

        print("[warmup] Complete")
    except Exception as e:
        print(f"[warmup] Thread failed: {e}")


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

    # Background warmup - populates dashboard cache so it doesn't time out
    if os.getenv("ENABLE_WARMUP", "1") == "1":
        threading.Thread(target=_warmup_cache, daemon=True).start()

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
