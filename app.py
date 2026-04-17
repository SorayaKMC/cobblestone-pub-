"""Cobblestone Pub Management App."""

from functools import wraps
from flask import Flask, redirect, url_for, request, Response, render_template
from datetime import date
import os
import re
import secrets
import threading
import db
import config


def pdf_basename(path):
    """Return a human-friendly filename from a stored pdf_path.

    Strips the directory and the `YYYYMMDD_HHMMSS_` upload-timestamp prefix
    that save_uploaded_pdf() prepends, so the original uploaded name is shown.
    """
    if not path:
        return ""
    name = os.path.basename(str(path))
    # Drop leading timestamp if present: 20260417_113245_Original.pdf -> Original.pdf
    return re.sub(r"^\d{8}_\d{6}_", "", name)


def _gmail_poll_loop():
    """Background thread: poll invoice@cobblestonepub.ie every 30 minutes.

    Disabled silently if GOOGLE_SERVICE_ACCOUNT_JSON is not set, so local
    development works without any Google credentials.
    """
    import time
    if not config.GOOGLE_SERVICE_ACCOUNT_JSON:
        print("[gmail] GOOGLE_SERVICE_ACCOUNT_JSON not set — inbox polling disabled")
        return
    print(f"[gmail] Inbox polling active (every {config.GMAIL_POLL_INTERVAL}s)")
    while True:
        try:
            from gmail_poller import check_inbox
            results = check_inbox()
            saved = sum(1 for r in results if r.get("invoice_id"))
            if saved:
                print(f"[gmail] Pulled {saved} new invoice(s) from inbox")
            elif results:
                print(f"[gmail] Checked inbox — nothing new")
        except Exception as e:
            print(f"[gmail] Poll error: {e}")
        time.sleep(config.GMAIL_POLL_INTERVAL)


def _warmup_cache():
    """Pre-populate dashboard cache in a background thread at startup.

    Designed for low memory: fetches one week at a time, writes to SQLite,
    then forces garbage collection before moving to the next week.
    Stays well under 100MB of peak memory.
    """
    try:
        import time
        import gc
        time.sleep(10)  # let app finish booting & handle first requests
        from routes.dashboard import _get_week_sales_with_daily, _get_week_payroll
        import square_client

        current_year, current_week = square_client.current_week()
        print(f"[warmup] Starting cache warmup for {current_year} W02-W{current_week}")

        for week in range(2, current_week + 1):
            try:
                # Fetch + cache current year
                _get_week_sales_with_daily(current_year, week)
                gc.collect()
                # Fetch + cache previous year (for YoY)
                _get_week_sales_with_daily(current_year - 1, week)
                gc.collect()
                # Fetch + cache payroll
                _get_week_payroll(current_year, week)
                gc.collect()
                print(f"[warmup] W{week:02d} cached")
                time.sleep(1)  # be gentle on Square's rate limits
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

    app.jinja_env.filters["pdf_basename"] = pdf_basename

    # Initialize database
    with app.app_context():
        db.init_db()

    # Background warmup - populates dashboard cache so it doesn't time out
    if os.getenv("ENABLE_WARMUP", "1") == "1":
        threading.Thread(target=_warmup_cache, daemon=True).start()

    # Background Gmail polling - checks invoice inbox every 30 minutes
    threading.Thread(target=_gmail_poll_loop, daemon=True).start()

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
    from routes import settings, payroll, dashboard, pto, bookkeeping
    app.register_blueprint(settings.bp)
    app.register_blueprint(payroll.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(pto.bp)
    app.register_blueprint(bookkeeping.bp)

    @app.route("/")
    def index():
        from datetime import datetime
        from routes.dashboard import _get_week_sales_with_daily
        import square_client as sq

        week_net = None
        week_label = ""
        week_dates = ""
        try:
            current_year, current_week = sq.current_week()
            sales = _get_week_sales_with_daily(current_year, current_week)
            if sales:
                week_net = round(sales["total"])
            week_label = f"W{current_week:02d}"
            start, end = sq.week_dates(current_year, current_week)
            start_dt = datetime.strptime(start, "%Y-%m-%d")
            end_dt = datetime.strptime(end, "%Y-%m-%d")
            week_dates = f"{start_dt.strftime('%-d %b')} – {end_dt.strftime('%-d %b')}"
        except Exception:
            pass

        hour = datetime.now().hour
        if hour < 12:
            greeting = "Good morning"
        elif hour < 17:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"

        return render_template("home.html",
            greeting=greeting,
            week_net=week_net,
            week_label=week_label,
            week_dates=week_dates,
        )

    @app.route("/healthz")
    def healthz():
        return "ok", 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, port=port)
