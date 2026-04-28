"""SQLite database layer for Cobblestone Pub app.

Stores employee categories, PTO data, and cache metadata.
Square API is the source of truth for sales, timecards, and team members.
"""

import sqlite3
import json
from datetime import datetime, date
import config


def get_db():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables and seed default data."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS employee_categories (
            team_member_id TEXT PRIMARY KEY,
            given_name TEXT NOT NULL,
            family_name TEXT NOT NULL,
            category TEXT NOT NULL CHECK(category IN (
                'Upper Management', 'Management', 'Staff'
            )),
            cleaning_amount REAL NOT NULL DEFAULT 0,
            weekly_salary REAL NOT NULL DEFAULT 0,
            pay_type TEXT NOT NULL DEFAULT 'hourly' CHECK(pay_type IN ('hourly', 'salaried')),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pto_accruals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_member_id TEXT NOT NULL,
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            hours_worked REAL NOT NULL DEFAULT 0,
            accrual_type TEXT NOT NULL CHECK(accrual_type IN ('hourly', 'salaried')),
            days_accrued REAL NOT NULL DEFAULT 0,
            running_balance REAL NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(team_member_id, period_start)
        );

        CREATE TABLE IF NOT EXISTS pto_taken (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_member_id TEXT NOT NULL,
            date DATE NOT NULL,
            days_taken REAL NOT NULL DEFAULT 1,
            hours_equivalent REAL NOT NULL DEFAULT 0,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(team_member_id, date)
        );

        CREATE TABLE IF NOT EXISTS pto_manual_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_member_id TEXT NOT NULL,
            adjustment_days REAL NOT NULL,
            reason TEXT NOT NULL,
            effective_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS cache_metadata (
            cache_key TEXT PRIMARY KEY,
            last_synced_at TIMESTAMP NOT NULL,
            data_json TEXT
        );

        CREATE TABLE IF NOT EXISTS weekly_tips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_member_id TEXT NOT NULL,
            iso_week TEXT NOT NULL,
            tips REAL NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(team_member_id, iso_week)
        );

        CREATE TABLE IF NOT EXISTS weekly_cleaning (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_member_id TEXT NOT NULL,
            iso_week TEXT NOT NULL,
            cleaning REAL NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(team_member_id, iso_week)
        );

        CREATE TABLE IF NOT EXISTS finalized_weeks (
            iso_week TEXT PRIMARY KEY,
            finalized_at TIMESTAMP NOT NULL,
            finalized_by TEXT
        );

        CREATE TABLE IF NOT EXISTS weekly_bonus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_member_id TEXT NOT NULL,
            iso_week TEXT NOT NULL,
            bonus REAL NOT NULL DEFAULT 0,
            note TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(team_member_id, iso_week)
        );

        -- Bookkeeping: suppliers + invoices
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            vat_number TEXT,
            default_vat_rate REAL NOT NULL DEFAULT 23,
            default_category TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER,
            supplier_name TEXT NOT NULL,
            invoice_date DATE NOT NULL,
            invoice_number TEXT,
            net_amount REAL NOT NULL DEFAULT 0,
            vat_amount REAL NOT NULL DEFAULT 0,
            total_amount REAL NOT NULL DEFAULT 0,
            vat_rate REAL NOT NULL DEFAULT 23,
            category TEXT,
            source TEXT NOT NULL DEFAULT 'manual',
            pdf_path TEXT,
            file_hash TEXT,
            status TEXT NOT NULL DEFAULT 'approved',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id),
            UNIQUE(file_hash)
        );

        CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(invoice_date);
        CREATE INDEX IF NOT EXISTS idx_invoices_supplier ON invoices(supplier_id);
        CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);

        -- Backroom / Upstairs venue bookings
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_token TEXT UNIQUE NOT NULL,
            venue TEXT NOT NULL DEFAULT 'Backroom',
            event_date DATE NOT NULL,
            day_of_week TEXT,
            door_time TEXT,
            start_time TEXT,
            end_time TEXT,
            status TEXT NOT NULL DEFAULT 'inquiry',
            event_type TEXT NOT NULL DEFAULT 'Gig',
            act_name TEXT NOT NULL,
            contact_name TEXT,
            contact_email TEXT,
            contact_phone TEXT,
            expected_attendance INTEGER,
            description TEXT,
            media_links TEXT,
            ticketing TEXT,
            ticket_price TEXT,
            ticket_link TEXT,
            door_person TEXT,
            door_fee_required INTEGER NOT NULL DEFAULT 0,
            venue_fee_required INTEGER NOT NULL DEFAULT 1,
            door_fee_paid_at TIMESTAMP,
            venue_fee_paid_at TIMESTAMP,
            door_fee_payment_id TEXT,
            venue_fee_payment_id TEXT,
            confirmation_sent_at TIMESTAMP,
            squarespace_published_at TIMESTAMP,
            google_calendar_event_id TEXT,
            announcement_date TEXT,
            support_act TEXT,
            promo_ok TEXT,
            notes TEXT,
            source TEXT NOT NULL DEFAULT 'web',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS booking_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booking_id) REFERENCES bookings(id)
        );

        CREATE TABLE IF NOT EXISTS booking_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booking_id) REFERENCES bookings(id)
        );

        CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(event_date);
        CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
        CREATE INDEX IF NOT EXISTS idx_bookings_venue ON bookings(venue);
        CREATE INDEX IF NOT EXISTS idx_bookings_token ON bookings(public_token);
        CREATE INDEX IF NOT EXISTS idx_booking_attachments_booking ON booking_attachments(booking_id);
        CREATE INDEX IF NOT EXISTS idx_booking_audit_booking ON booking_audit(booking_id);
    """)

    # Migration: add columns to employee_categories if missing
    columns = [row[1] for row in cursor.execute("PRAGMA table_info(employee_categories)").fetchall()]
    if "weekly_salary" not in columns:
        cursor.execute("ALTER TABLE employee_categories ADD COLUMN weekly_salary REAL NOT NULL DEFAULT 0")
    if "pay_type" not in columns:
        cursor.execute("ALTER TABLE employee_categories ADD COLUMN pay_type TEXT NOT NULL DEFAULT 'hourly'")
    if "is_active" not in columns:
        cursor.execute("ALTER TABLE employee_categories ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

    # Migration: add source column to pto_accruals (tracks where accrual came from)
    acc_cols = [row[1] for row in cursor.execute("PRAGMA table_info(pto_accruals)").fetchall()]
    if "source" not in acc_cols:
        cursor.execute("ALTER TABLE pto_accruals ADD COLUMN source TEXT NOT NULL DEFAULT 'square'")

    # Migration: add cancelled_by column to bookings (tracks who cancelled: 'band' | 'pub' | 'system')
    bk_cols = [row[1] for row in cursor.execute("PRAGMA table_info(bookings)").fetchall()]
    if "cancelled_by" not in bk_cols:
        cursor.execute("ALTER TABLE bookings ADD COLUMN cancelled_by TEXT")

    # Seed default categories if table is empty
    count = cursor.execute("SELECT COUNT(*) FROM employee_categories").fetchone()[0]
    if count == 0:
        for tm_id, (first, last, cat) in config.DEFAULT_CATEGORIES.items():
            cleaning = config.DEFAULT_CLEANING.get(tm_id, 0)
            salary_info = config.DEFAULT_SALARIES.get(tm_id, (0, "hourly"))
            cursor.execute(
                "INSERT INTO employee_categories (team_member_id, given_name, family_name, category, cleaning_amount, weekly_salary, pay_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (tm_id, first, last, cat, cleaning, salary_info[0], salary_info[1]),
            )

    # Migration: ensure DEFAULT_CLEANING values are applied to existing rows that
    # still have cleaning_amount=0 (catches DBs seeded before defaults were set).
    for tm_id, default_amount in config.DEFAULT_CLEANING.items():
        cursor.execute(
            """UPDATE employee_categories
               SET cleaning_amount = ?
               WHERE team_member_id = ? AND cleaning_amount = 0""",
            (default_amount, tm_id),
        )

    # Seed suppliers if the table is empty
    supplier_count = cursor.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0]
    if supplier_count == 0:
        for name, vat_rate, category in config.DEFAULT_SUPPLIERS:
            cursor.execute(
                "INSERT OR IGNORE INTO suppliers (name, default_vat_rate, default_category) VALUES (?, ?, ?)",
                (name, vat_rate, category),
            )

    conn.commit()
    conn.close()


# --- Employee Categories ---

def get_employee_categories():
    """Get all employee category assignments. Returns list of Row objects."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM employee_categories ORDER BY category, family_name"
    ).fetchall()
    conn.close()
    return rows


def get_employee_category(team_member_id):
    """Get category for a single employee."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM employee_categories WHERE team_member_id = ?",
        (team_member_id,),
    ).fetchone()
    conn.close()
    return row


def update_employee_category(team_member_id, given_name, family_name, category, cleaning_amount=0, weekly_salary=0, pay_type="hourly"):
    """Update or insert an employee category. Does NOT overwrite is_active (preserves former-employee flag)."""
    conn = get_db()
    conn.execute(
        """INSERT INTO employee_categories (team_member_id, given_name, family_name, category, cleaning_amount, weekly_salary, pay_type, is_active, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
           ON CONFLICT(team_member_id) DO UPDATE SET
               given_name=excluded.given_name,
               family_name=excluded.family_name,
               category=excluded.category,
               cleaning_amount=excluded.cleaning_amount,
               weekly_salary=excluded.weekly_salary,
               pay_type=excluded.pay_type,
               updated_at=excluded.updated_at""",
        (team_member_id, given_name, family_name, category, cleaning_amount, weekly_salary, pay_type, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def bulk_update_categories(updates):
    """Update multiple employee categories at once (including is_active)."""
    conn = get_db()
    for u in updates:
        conn.execute(
            """INSERT INTO employee_categories (team_member_id, given_name, family_name, category, cleaning_amount, weekly_salary, pay_type, is_active, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(team_member_id) DO UPDATE SET
                   given_name=excluded.given_name,
                   family_name=excluded.family_name,
                   category=excluded.category,
                   cleaning_amount=excluded.cleaning_amount,
                   weekly_salary=excluded.weekly_salary,
                   pay_type=excluded.pay_type,
                   is_active=excluded.is_active,
                   updated_at=excluded.updated_at""",
            (u["team_member_id"], u["given_name"], u["family_name"], u["category"],
             u.get("cleaning_amount", 0), u.get("weekly_salary", 0), u.get("pay_type", "hourly"),
             u.get("is_active", 1), datetime.now().isoformat()),
        )
    conn.commit()
    conn.close()


# --- PTO ---

def get_pto_summary():
    """Get PTO summary for all employees.

    Returns list of dicts with team_member_id, name, total_accrued, total_taken, balance.
    """
    conn = get_db()
    rows = conn.execute("""
        SELECT
            ec.team_member_id,
            ec.given_name,
            ec.family_name,
            ec.is_active,
            COALESCE(accrued.total_days, 0) as total_accrued,
            COALESCE(taken.total_days, 0) as total_taken,
            COALESCE(adj.total_adj, 0) as total_adjustments
        FROM employee_categories ec
        LEFT JOIN (
            SELECT team_member_id, SUM(days_accrued) as total_days
            FROM pto_accruals GROUP BY team_member_id
        ) accrued ON ec.team_member_id = accrued.team_member_id
        LEFT JOIN (
            SELECT team_member_id, SUM(days_taken) as total_days
            FROM pto_taken GROUP BY team_member_id
        ) taken ON ec.team_member_id = taken.team_member_id
        LEFT JOIN (
            SELECT team_member_id, SUM(adjustment_days) as total_adj
            FROM pto_manual_adjustments GROUP BY team_member_id
        ) adj ON ec.team_member_id = adj.team_member_id
        ORDER BY ec.family_name
    """).fetchall()
    conn.close()

    results = []
    for r in rows:
        balance = min(r["total_accrued"] + r["total_adjustments"] - r["total_taken"], 21)
        results.append({
            "team_member_id": r["team_member_id"],
            "given_name": r["given_name"],
            "family_name": r["family_name"],
            "is_active": r["is_active"] if "is_active" in r.keys() else 1,
            "total_accrued": round(r["total_accrued"], 2),
            "total_taken": round(r["total_taken"], 2),
            "total_adjustments": round(r["total_adjustments"], 2),
            "balance": round(max(balance, 0), 2),
        })
    return results


def update_supplier_category(supplier_id, category):
    """Update a supplier's default category based on the last invoice choice."""
    conn = get_db()
    conn.execute("UPDATE suppliers SET default_category = ? WHERE id = ?", (category, supplier_id))
    conn.commit()
    conn.close()


def add_pto_accrual(team_member_id, period_start, period_end, hours_worked, accrual_type, days_accrued, running_balance, source="square", respect_protected=False):
    """Record a PTO accrual period.

    Args:
        source: 'v4_import' for historical data, 'square' for live recalc, 'manual' for edits
        respect_protected: if True, skip if an existing record is marked as v4_import
    """
    conn = get_db()

    if respect_protected:
        existing = conn.execute(
            "SELECT source FROM pto_accruals WHERE team_member_id=? AND period_start=?",
            (team_member_id, period_start),
        ).fetchone()
        if existing and existing["source"] == "v4_import":
            conn.close()
            return False  # skipped

    conn.execute(
        """INSERT INTO pto_accruals (team_member_id, period_start, period_end, hours_worked, accrual_type, days_accrued, running_balance, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(team_member_id, period_start) DO UPDATE SET
               period_end=excluded.period_end,
               hours_worked=excluded.hours_worked,
               accrual_type=excluded.accrual_type,
               days_accrued=excluded.days_accrued,
               running_balance=excluded.running_balance,
               source=excluded.source""",
        (team_member_id, period_start, period_end, hours_worked, accrual_type, days_accrued, running_balance, source),
    )
    conn.commit()
    conn.close()
    return True


def is_pto_accrual_protected(team_member_id, period_start):
    """Check if a given week's accrual is protected (e.g. imported from V4 spreadsheet)."""
    conn = get_db()
    row = conn.execute(
        "SELECT source FROM pto_accruals WHERE team_member_id=? AND period_start=?",
        (team_member_id, period_start),
    ).fetchone()
    conn.close()
    return row is not None and row["source"] == "v4_import"


def add_pto_taken(team_member_id, date, days_taken, hours_equivalent, reason=""):
    """Record PTO days taken."""
    conn = get_db()
    conn.execute(
        """INSERT INTO pto_taken (team_member_id, date, days_taken, hours_equivalent, reason)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(team_member_id, date) DO UPDATE SET
               days_taken=excluded.days_taken,
               hours_equivalent=excluded.hours_equivalent,
               reason=excluded.reason""",
        (team_member_id, date, days_taken, hours_equivalent, reason),
    )
    conn.commit()
    conn.close()


def get_pto_taken_log(team_member_id=None):
    """Get PTO taken records, optionally filtered by employee."""
    conn = get_db()
    if team_member_id:
        rows = conn.execute(
            "SELECT * FROM pto_taken WHERE team_member_id = ? ORDER BY date DESC",
            (team_member_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM pto_taken ORDER BY date DESC").fetchall()
    conn.close()
    return rows


def get_pto_taken_for_week(start_date, end_date):
    """Return PTO taken (hours and days) per employee for a date range.

    Used by the payroll page to auto-populate the Holiday Pay column from
    the PTO tracker — no double-entry needed.

    Returns dict: {team_member_id: {"hours": float, "days": float}}
    """
    conn = get_db()
    rows = conn.execute(
        """SELECT team_member_id,
                  COALESCE(SUM(hours_equivalent), 0) AS total_hours,
                  COALESCE(SUM(days_taken), 0) AS total_days
           FROM pto_taken
           WHERE date BETWEEN ? AND ?
           GROUP BY team_member_id""",
        (start_date, end_date),
    ).fetchall()
    conn.close()
    return {
        r["team_member_id"]: {"hours": float(r["total_hours"]), "days": float(r["total_days"])}
        for r in rows
    }


def add_pto_adjustment(team_member_id, adjustment_days, reason, effective_date):
    """Record a manual PTO adjustment."""
    conn = get_db()
    conn.execute(
        "INSERT INTO pto_manual_adjustments (team_member_id, adjustment_days, reason, effective_date) VALUES (?, ?, ?, ?)",
        (team_member_id, adjustment_days, reason, effective_date),
    )
    conn.commit()
    conn.close()


# --- Weekly Tips (manually entered, NOT from Square) ---

def get_weekly_tips(iso_week):
    """Get all employees' tips for an ISO week. Returns dict {team_member_id: tips}."""
    conn = get_db()
    rows = conn.execute(
        "SELECT team_member_id, tips FROM weekly_tips WHERE iso_week = ?",
        (iso_week,),
    ).fetchall()
    conn.close()
    return {r["team_member_id"]: r["tips"] for r in rows}


def set_weekly_tip(team_member_id, iso_week, tips):
    """Save a manual tip amount for an employee for a specific week."""
    conn = get_db()
    conn.execute(
        """INSERT INTO weekly_tips (team_member_id, iso_week, tips, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(team_member_id, iso_week) DO UPDATE SET
               tips=excluded.tips,
               updated_at=excluded.updated_at""",
        (team_member_id, iso_week, tips, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def bulk_set_weekly_tips(iso_week, tips_by_employee):
    """Save multiple tips at once. tips_by_employee = {team_member_id: tips}."""
    conn = get_db()
    now = datetime.now().isoformat()
    for tm_id, tips in tips_by_employee.items():
        conn.execute(
            """INSERT INTO weekly_tips (team_member_id, iso_week, tips, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(team_member_id, iso_week) DO UPDATE SET
                   tips=excluded.tips,
                   updated_at=excluded.updated_at""",
            (tm_id, iso_week, float(tips or 0), now),
        )
    conn.commit()
    conn.close()


# --- Weekly Cleaning (editable per week, defaults to employee_categories.cleaning_amount) ---

def get_weekly_cleaning(iso_week):
    """Returns {team_member_id: cleaning_amount} for any overrides this week."""
    conn = get_db()
    rows = conn.execute(
        "SELECT team_member_id, cleaning FROM weekly_cleaning WHERE iso_week = ?",
        (iso_week,),
    ).fetchall()
    conn.close()
    return {r["team_member_id"]: r["cleaning"] for r in rows}


def bulk_set_weekly_cleaning(iso_week, cleaning_by_employee):
    """Save multiple cleaning overrides at once."""
    conn = get_db()
    now = datetime.now().isoformat()
    for tm_id, amount in cleaning_by_employee.items():
        conn.execute(
            """INSERT INTO weekly_cleaning (team_member_id, iso_week, cleaning, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(team_member_id, iso_week) DO UPDATE SET
                   cleaning=excluded.cleaning,
                   updated_at=excluded.updated_at""",
            (tm_id, iso_week, float(amount or 0), now),
        )
    conn.commit()
    conn.close()


# --- Weekly Bonus (manually entered per week, same rules as tips) ---

def get_weekly_bonus(iso_week):
    """Returns {team_member_id: bonus_amount} for the given week."""
    conn = get_db()
    rows = conn.execute(
        "SELECT team_member_id, bonus FROM weekly_bonus WHERE iso_week = ?",
        (iso_week,),
    ).fetchall()
    conn.close()
    return {r["team_member_id"]: r["bonus"] for r in rows}


def bulk_set_weekly_bonus(iso_week, bonus_by_employee):
    """Save multiple bonus amounts at once."""
    conn = get_db()
    now = datetime.now().isoformat()
    for tm_id, amount in bonus_by_employee.items():
        conn.execute(
            """INSERT INTO weekly_bonus (team_member_id, iso_week, bonus, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(team_member_id, iso_week) DO UPDATE SET
                   bonus=excluded.bonus,
                   updated_at=excluded.updated_at""",
            (tm_id, iso_week, float(amount or 0), now),
        )
    conn.commit()
    conn.close()


# --- Week finalization (locks payroll from editing) ---

def is_week_finalized(iso_week):
    """Check if a payroll week has been finalized."""
    conn = get_db()
    row = conn.execute(
        "SELECT iso_week FROM finalized_weeks WHERE iso_week = ?",
        (iso_week,),
    ).fetchone()
    conn.close()
    return row is not None


def finalize_week(iso_week, finalized_by="admin"):
    """Mark a week as finalized (locks payroll data)."""
    conn = get_db()
    conn.execute(
        """INSERT INTO finalized_weeks (iso_week, finalized_at, finalized_by)
           VALUES (?, ?, ?)
           ON CONFLICT(iso_week) DO NOTHING""",
        (iso_week, datetime.now().isoformat(), finalized_by),
    )
    conn.commit()
    conn.close()


def unfinalize_week(iso_week):
    """Unlock a finalized week."""
    conn = get_db()
    conn.execute("DELETE FROM finalized_weeks WHERE iso_week = ?", (iso_week,))
    conn.commit()
    conn.close()


def get_finalized_weeks():
    """Return list of finalized week info."""
    conn = get_db()
    rows = conn.execute(
        "SELECT iso_week, finalized_at, finalized_by FROM finalized_weeks ORDER BY iso_week DESC"
    ).fetchall()
    conn.close()
    return rows


# --- Bookkeeping: Suppliers + Invoices ---

def list_suppliers():
    conn = get_db()
    rows = conn.execute("SELECT * FROM suppliers ORDER BY name").fetchall()
    conn.close()
    return rows


def find_supplier_by_name(name):
    """Match supplier name - exact, then substring-in-either-direction.

    E.g. extracted 'Diageo Ireland' should match directory 'Diageo',
    and extracted 'BWG' should match directory 'BWG Foods'.
    """
    if not name:
        return None
    conn = get_db()
    name_low = name.lower().strip()

    # 1. Exact (case-insensitive)
    row = conn.execute("SELECT * FROM suppliers WHERE LOWER(name) = ?", (name_low,)).fetchone()
    if row:
        conn.close()
        return row

    # 2. Directory name is contained in extracted name (e.g. directory="Diageo", extracted="Diageo Ireland")
    all_suppliers = conn.execute("SELECT * FROM suppliers ORDER BY LENGTH(name) DESC").fetchall()
    for s in all_suppliers:
        if s["name"].lower() in name_low:
            conn.close()
            return s

    # 3. Extracted name is contained in directory name (e.g. extracted="BWG", directory="BWG Foods")
    for s in all_suppliers:
        if name_low in s["name"].lower():
            conn.close()
            return s

    conn.close()
    return None


def add_supplier(name, default_vat_rate=23, default_category=None, vat_number=None):
    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO suppliers (name, default_vat_rate, default_category, vat_number)
           VALUES (?, ?, ?, ?)""",
        (name, default_vat_rate, default_category, vat_number),
    )
    conn.commit()
    conn.close()


def update_supplier(supplier_id, name, default_vat_rate, default_category, vat_number=None):
    conn = get_db()
    conn.execute(
        """UPDATE suppliers
           SET name=?, default_vat_rate=?, default_category=?, vat_number=?
           WHERE id=?""",
        (name, default_vat_rate, default_category, vat_number, supplier_id),
    )
    conn.commit()
    conn.close()


def list_invoices(start_date=None, end_date=None, supplier_id=None, category=None, status=None, limit=500):
    """Get invoices with optional filters. Returns list of rows."""
    conn = get_db()
    sql = """SELECT i.*, s.name AS supplier_name_resolved, s.default_category
             FROM invoices i
             LEFT JOIN suppliers s ON i.supplier_id = s.id
             WHERE 1=1"""
    params = []
    if start_date:
        sql += " AND i.invoice_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND i.invoice_date <= ?"
        params.append(end_date)
    if supplier_id:
        sql += " AND i.supplier_id = ?"
        params.append(supplier_id)
    if category:
        sql += " AND i.category = ?"
        params.append(category)
    if status:
        sql += " AND i.status = ?"
        params.append(status)
    sql += " ORDER BY i.invoice_date DESC, i.id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def get_invoice(invoice_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    conn.close()
    return row


def save_invoice(data, invoice_id=None):
    """Insert a new invoice or update an existing one. Returns invoice id.

    data: dict with keys: supplier_id, supplier_name, invoice_date, invoice_number,
          net_amount, vat_amount, total_amount, vat_rate, category,
          source, pdf_path, file_hash, status, notes
    """
    conn = get_db()
    now = datetime.now().isoformat()

    if invoice_id:
        conn.execute(
            """UPDATE invoices SET
               supplier_id=?, supplier_name=?, invoice_date=?, invoice_number=?,
               net_amount=?, vat_amount=?, total_amount=?, vat_rate=?, category=?,
               status=?, notes=?, updated_at=?
               WHERE id=?""",
            (data.get("supplier_id"), data.get("supplier_name"),
             data.get("invoice_date"), data.get("invoice_number"),
             data.get("net_amount", 0), data.get("vat_amount", 0),
             data.get("total_amount", 0), data.get("vat_rate", 23),
             data.get("category"), data.get("status", "approved"),
             data.get("notes"), now, invoice_id),
        )
        new_id = invoice_id
    else:
        cursor = conn.execute(
            """INSERT INTO invoices (supplier_id, supplier_name, invoice_date, invoice_number,
                net_amount, vat_amount, total_amount, vat_rate, category,
                source, pdf_path, file_hash, status, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data.get("supplier_id"), data.get("supplier_name"),
             data.get("invoice_date"), data.get("invoice_number"),
             data.get("net_amount", 0), data.get("vat_amount", 0),
             data.get("total_amount", 0), data.get("vat_rate", 23),
             data.get("category"), data.get("source", "manual"),
             data.get("pdf_path"), data.get("file_hash"),
             data.get("status", "approved"), data.get("notes"), now),
        )
        new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id


def delete_invoice(invoice_id):
    conn = get_db()
    conn.execute("DELETE FROM invoices WHERE id=?", (invoice_id,))
    conn.commit()
    conn.close()


def monthly_vat_totals(year):
    """Sum VAT amounts per month for the given year. Only 'approved' invoices.

    Returns dict {month_int: {net, vat, total, count}}.
    """
    conn = get_db()
    rows = conn.execute(
        """SELECT CAST(strftime('%m', invoice_date) AS INTEGER) AS m,
                  SUM(net_amount) AS net,
                  SUM(vat_amount) AS vat,
                  SUM(total_amount) AS total,
                  COUNT(*) AS cnt
           FROM invoices
           WHERE status='approved' AND strftime('%Y', invoice_date) = ?
           GROUP BY m""",
        (str(year),),
    ).fetchall()
    conn.close()
    return {r["m"]: {"net": r["net"] or 0, "vat": r["vat"] or 0,
                     "total": r["total"] or 0, "count": r["cnt"]}
            for r in rows}


# --- Cache ---

def get_cache(key):
    """Get cached data. Returns parsed JSON or None."""
    conn = get_db()
    row = conn.execute("SELECT data_json, last_synced_at FROM cache_metadata WHERE cache_key = ?", (key,)).fetchone()
    conn.close()
    if row and row["data_json"]:
        return json.loads(row["data_json"]), row["last_synced_at"]
    return None, None


def set_cache(key, data):
    """Store data in cache."""
    conn = get_db()
    conn.execute(
        """INSERT INTO cache_metadata (cache_key, last_synced_at, data_json)
           VALUES (?, ?, ?)
           ON CONFLICT(cache_key) DO UPDATE SET
               last_synced_at=excluded.last_synced_at,
               data_json=excluded.data_json""",
        (key, datetime.now().isoformat(), json.dumps(data, default=str)),
    )
    conn.commit()
    conn.close()


# --- Backroom / Upstairs Bookings ---

import secrets as _secrets


# Field set used by save_booking - keeps INSERT/UPDATE columns aligned.
_BOOKING_FIELDS = (
    "venue", "event_date", "day_of_week",
    "door_time", "start_time", "end_time",
    "status", "event_type", "act_name",
    "contact_name", "contact_email", "contact_phone",
    "expected_attendance", "description", "media_links",
    "ticketing", "ticket_price", "ticket_link",
    "door_person", "door_fee_required", "venue_fee_required",
    "announcement_date", "support_act", "promo_ok", "notes", "source",
)


def _new_booking_token():
    """Generate a URL-safe public booking token."""
    return _secrets.token_urlsafe(16)


def list_bookings(status=None, venue=None, start_date=None, end_date=None,
                  event_type=None, limit=1000):
    """Get bookings with optional filters. Returns rows ordered by event_date asc."""
    conn = get_db()
    sql = "SELECT * FROM bookings WHERE 1=1"
    params = []
    if status:
        if isinstance(status, (list, tuple)):
            placeholders = ",".join("?" * len(status))
            sql += f" AND status IN ({placeholders})"
            params.extend(status)
        else:
            sql += " AND status = ?"
            params.append(status)
    if venue:
        sql += " AND venue = ?"
        params.append(venue)
    if event_type:
        sql += " AND event_type = ?"
        params.append(event_type)
    if start_date:
        sql += " AND event_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND event_date <= ?"
        params.append(end_date)
    sql += " ORDER BY event_date ASC, id ASC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def get_booking(id_or_token):
    """Look up a booking by integer id or by public_token string."""
    conn = get_db()
    if isinstance(id_or_token, int) or (isinstance(id_or_token, str) and id_or_token.isdigit()):
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (int(id_or_token),)).fetchone()
    else:
        row = conn.execute("SELECT * FROM bookings WHERE public_token = ?", (id_or_token,)).fetchone()
    conn.close()
    return row


def save_booking(data, booking_id=None):
    """Insert a new booking or update an existing one. Returns the booking id.

    On insert, generates a unique public_token if one isn't supplied.
    `data` is a dict with keys from _BOOKING_FIELDS.
    """
    conn = get_db()
    now = datetime.now().isoformat()

    if booking_id:
        sets = ", ".join(f"{f}=?" for f in _BOOKING_FIELDS)
        params = [data.get(f) for f in _BOOKING_FIELDS] + [now, booking_id]
        conn.execute(f"UPDATE bookings SET {sets}, updated_at=? WHERE id=?", params)
        new_id = booking_id
    else:
        token = data.get("public_token") or _new_booking_token()
        cols = ["public_token"] + list(_BOOKING_FIELDS) + ["updated_at"]
        placeholders = ",".join("?" * len(cols))
        values = [token] + [data.get(f) for f in _BOOKING_FIELDS] + [now]
        cursor = conn.execute(
            f"INSERT INTO bookings ({','.join(cols)}) VALUES ({placeholders})", values
        )
        new_id = cursor.lastrowid

    conn.commit()
    conn.close()
    return new_id


def update_booking_status(booking_id, new_status, actor="system", detail=None):
    """Set status and write an audit row. Returns True on success."""
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE bookings SET status=?, updated_at=? WHERE id=?",
        (new_status, now, booking_id),
    )
    conn.execute(
        "INSERT INTO booking_audit (booking_id, actor, action, detail) VALUES (?, ?, ?, ?)",
        (booking_id, actor, f"status:{new_status}", detail),
    )
    conn.commit()
    conn.close()
    return True


def cancel_booking(booking_id, cancelled_by="pub", actor="internal", detail=None):
    """Cancel a booking and record who initiated the cancellation.

    cancelled_by — 'band' | 'pub' | 'system'
    Writes an audit row automatically.
    """
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE bookings SET status='cancelled', cancelled_by=?, updated_at=? WHERE id=?",
        (cancelled_by, now, booking_id),
    )
    conn.execute(
        "INSERT INTO booking_audit (booking_id, actor, action, detail) VALUES (?, ?, ?, ?)",
        (booking_id, actor, "status:cancelled",
         detail or f"Cancelled by {cancelled_by}"),
    )
    conn.commit()
    conn.close()
    return True


def update_booking_field(booking_id, field, value, actor="system"):
    """Update a single column on a booking + write audit row.

    Restricted to a safe column list to avoid SQL injection via the field name.
    """
    safe = {
        "venue_fee_paid_at", "door_fee_paid_at",
        "venue_fee_payment_id", "door_fee_payment_id",
        "confirmation_sent_at", "squarespace_published_at",
        "google_calendar_event_id", "notes",
    }
    if field not in safe:
        raise ValueError(f"Field '{field}' not allowed for direct update")
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        f"UPDATE bookings SET {field}=?, updated_at=? WHERE id=?",
        (value, now, booking_id),
    )
    conn.execute(
        "INSERT INTO booking_audit (booking_id, actor, action, detail) VALUES (?, ?, ?, ?)",
        (booking_id, actor, f"set:{field}", str(value)[:200] if value else "cleared"),
    )
    conn.commit()
    conn.close()


def add_booking_audit(booking_id, actor, action, detail=None):
    """Append a free-form audit entry."""
    conn = get_db()
    conn.execute(
        "INSERT INTO booking_audit (booking_id, actor, action, detail) VALUES (?, ?, ?, ?)",
        (booking_id, actor, action, detail),
    )
    conn.commit()
    conn.close()


def get_booking_audit(booking_id):
    """Return audit log for a booking, newest first."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM booking_audit WHERE booking_id=? ORDER BY id DESC",
        (booking_id,),
    ).fetchall()
    conn.close()
    return rows


def get_booking_attachments(booking_id):
    """Return all attachments for a booking, newest first."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM booking_attachments WHERE booking_id=? ORDER BY id DESC",
        (booking_id,),
    ).fetchall()
    conn.close()
    return rows


def add_booking_attachment(booking_id, kind, filename, file_path):
    """Record an uploaded attachment."""
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO booking_attachments (booking_id, kind, filename, file_path) VALUES (?, ?, ?, ?)",
        (booking_id, kind, filename, file_path),
    )
    conn.commit()
    conn.close()
    return cursor.lastrowid


def booking_counts():
    """Return summary counts for the tracker top bar."""
    today = date.today().isoformat()
    conn = get_db()
    inquiry = conn.execute(
        "SELECT COUNT(*) FROM bookings WHERE status='inquiry' AND event_date >= ?",
        (today,),
    ).fetchone()[0]
    tentative = conn.execute(
        "SELECT COUNT(*) FROM bookings WHERE status='tentative' AND event_date >= ?",
        (today,),
    ).fetchone()[0]
    confirmed_upcoming = conn.execute(
        "SELECT COUNT(*) FROM bookings WHERE status='confirmed' AND event_date >= ?",
        (today,),
    ).fetchone()[0]
    unpaid_fees = conn.execute(
        """SELECT COUNT(*) FROM bookings
           WHERE status IN ('confirmed','completed')
             AND ((venue_fee_required=1 AND venue_fee_paid_at IS NULL)
                  OR (door_fee_required=1 AND door_fee_paid_at IS NULL))""",
    ).fetchone()[0]
    needs_publishing = conn.execute(
        """SELECT COUNT(*) FROM bookings
           WHERE status='confirmed' AND event_date >= ?
             AND squarespace_published_at IS NULL""",
        (today,),
    ).fetchone()[0]
    conn.close()
    return {
        "inquiry": inquiry,
        "tentative": tentative,
        "confirmed_upcoming": confirmed_upcoming,
        "unpaid_fees": unpaid_fees,
        "needs_publishing": needs_publishing,
    }
