"""SQLite database layer for Cobblestone Pub app.

Stores employee categories, PTO data, and cache metadata.
Square API is the source of truth for sales, timecards, and team members.
"""

import sqlite3
import json
from datetime import datetime
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
    """)

    # Migration: add weekly_salary and pay_type columns if missing
    columns = [row[1] for row in cursor.execute("PRAGMA table_info(employee_categories)").fetchall()]
    if "weekly_salary" not in columns:
        cursor.execute("ALTER TABLE employee_categories ADD COLUMN weekly_salary REAL NOT NULL DEFAULT 0")
    if "pay_type" not in columns:
        cursor.execute("ALTER TABLE employee_categories ADD COLUMN pay_type TEXT NOT NULL DEFAULT 'hourly'")

    # Migration: add source column to pto_accruals (tracks where accrual came from)
    acc_cols = [row[1] for row in cursor.execute("PRAGMA table_info(pto_accruals)").fetchall()]
    if "source" not in acc_cols:
        cursor.execute("ALTER TABLE pto_accruals ADD COLUMN source TEXT NOT NULL DEFAULT 'square'")

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
    """Update or insert an employee category."""
    conn = get_db()
    conn.execute(
        """INSERT INTO employee_categories (team_member_id, given_name, family_name, category, cleaning_amount, weekly_salary, pay_type, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
    """Update multiple employee categories at once."""
    conn = get_db()
    for u in updates:
        conn.execute(
            """INSERT INTO employee_categories (team_member_id, given_name, family_name, category, cleaning_amount, weekly_salary, pay_type, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(team_member_id) DO UPDATE SET
                   given_name=excluded.given_name,
                   family_name=excluded.family_name,
                   category=excluded.category,
                   cleaning_amount=excluded.cleaning_amount,
                   weekly_salary=excluded.weekly_salary,
                   pay_type=excluded.pay_type,
                   updated_at=excluded.updated_at""",
            (u["team_member_id"], u["given_name"], u["family_name"], u["category"],
             u.get("cleaning_amount", 0), u.get("weekly_salary", 0), u.get("pay_type", "hourly"),
             datetime.now().isoformat()),
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
            "total_accrued": round(r["total_accrued"], 2),
            "total_taken": round(r["total_taken"], 2),
            "total_adjustments": round(r["total_adjustments"], 2),
            "balance": round(max(balance, 0), 2),
        })
    return results


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
