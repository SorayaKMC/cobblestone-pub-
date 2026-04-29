"""Square API client for Cobblestone Pub.

All money values returned as Decimal in EUR (converted from Square's cent integers).
All datetime handling uses Europe/Dublin timezone.
"""

import requests
from decimal import Decimal
from datetime import datetime, timedelta, timezone
import config


def _headers():
    return {
        "Authorization": f"Bearer {config.SQUARE_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "Square-Version": "2025-04-16",
    }


def _money_to_decimal(money_obj):
    """Convert Square money object (amount in cents) to Decimal EUR."""
    if not money_obj:
        return Decimal("0.00")
    return Decimal(str(money_obj.get("amount", 0))) / Decimal("100")


def _paginated_post(endpoint, body, result_key):
    """POST with cursor-based pagination. Returns all results."""
    url = f"{config.SQUARE_BASE_URL}/{endpoint}"
    all_results = []
    cursor = None
    while True:
        if cursor:
            body["cursor"] = cursor
        resp = requests.post(url, headers=_headers(), json=body)
        resp.raise_for_status()
        data = resp.json()
        all_results.extend(data.get(result_key, []))
        cursor = data.get("cursor")
        if not cursor:
            break
    return all_results


def _paginated_get(endpoint, params=None, result_key=None):
    """GET with cursor-based pagination."""
    url = f"{config.SQUARE_BASE_URL}/{endpoint}"
    all_results = []
    cursor = None
    if params is None:
        params = {}
    while True:
        if cursor:
            params["cursor"] = cursor
        resp = requests.get(url, headers=_headers(), params=params)
        resp.raise_for_status()
        data = resp.json()
        if result_key:
            all_results.extend(data.get(result_key, []))
        else:
            return data
        cursor = data.get("cursor")
        if not cursor:
            break
    return all_results


# --- Team Members ---

def get_team_members():
    """Fetch all active team members with wage data.

    Returns list of dicts:
        id, given_name, family_name, status, job_title, pay_type,
        hourly_rate (Decimal), annual_rate (Decimal), weekly_hours, is_owner
    """
    body = {
        "query": {
            "filter": {
                "location_ids": config.ALL_LOCATION_IDS,
                "status": "ACTIVE",
            }
        },
        "limit": 100,
    }
    raw_members = _paginated_post("team-members/search", body, "team_members")

    members = []
    for m in raw_members:
        wage_setting = m.get("wage_setting", {})
        job_assignments = wage_setting.get("job_assignments", [])

        # Use first job assignment for primary wage info
        primary_job = job_assignments[0] if job_assignments else {}

        pay_type = primary_job.get("pay_type", "NONE")
        hourly_rate = _money_to_decimal(primary_job.get("hourly_rate"))
        annual_rate = Decimal(str(primary_job.get("annual_rate", {}).get("amount", 0))) / Decimal("100") if primary_job.get("annual_rate") else Decimal("0")
        weekly_hours = primary_job.get("weekly_hours") or 0

        members.append({
            "id": m["id"],
            "given_name": m.get("given_name", ""),
            "family_name": m.get("family_name", ""),
            "status": m.get("status", "ACTIVE"),
            "job_title": primary_job.get("job_title", ""),
            "pay_type": pay_type,
            "hourly_rate": hourly_rate,
            "annual_rate": annual_rate,
            "weekly_hours": weekly_hours,
            "is_owner": m.get("is_owner", False),
        })

    return members


def get_team_member_wages():
    """Fetch wage data keyed by team_member_id."""
    raw = _paginated_get("labor/team-member-wages", result_key="team_member_wages")
    wages = {}
    for w in raw:
        tm_id = w.get("team_member_id")
        if tm_id:
            wages[tm_id] = {
                "hourly_rate": _money_to_decimal(w.get("hourly_rate")),
                "job_title": w.get("title", ""),
            }
    return wages


# --- Timecards ---

def get_timecards(start_date, end_date):
    """Fetch timecards for a date range.

    Args:
        start_date: 'YYYY-MM-DD' string (Monday)
        end_date: 'YYYY-MM-DD' string (Sunday)

    Returns list of processed timecard dicts:
        team_member_id, location_id, start_at, end_at,
        total_minutes, break_minutes, paid_minutes,
        regular_hours (Decimal), overtime_hours (Decimal),
        doubletime_hours (Decimal), status,
        declared_cash_tip (Decimal)
    """
    body = {
        "query": {
            "filter": {
                "location_ids": config.ALL_LOCATION_IDS,
                "workday": {
                    "date_range": {
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                    "default_timezone": config.TIMEZONE,
                },
            },
            "sort": {
                "field": "START_AT",
                "order": "ASC",
            },
        },
        "limit": 200,
    }

    raw_timecards = _paginated_post("labor/timecards/search", body, "timecards")
    return [_process_timecard(tc) for tc in raw_timecards]


def _process_timecard(tc):
    """Process a raw Square timecard into clean data."""
    start_at = datetime.fromisoformat(tc["start_at"].replace("Z", "+00:00"))
    end_at_str = tc.get("end_at")

    if end_at_str:
        end_at = datetime.fromisoformat(end_at_str.replace("Z", "+00:00"))
        total_minutes = Decimal(str((end_at - start_at).total_seconds())) / Decimal("60")
    else:
        end_at = None
        total_minutes = Decimal("0")

    # Calculate unpaid break time
    break_minutes = Decimal("0")
    for brk in tc.get("breaks", []):
        if not brk.get("is_paid", False):
            brk_start = datetime.fromisoformat(brk["start_at"].replace("Z", "+00:00"))
            brk_end_str = brk.get("end_at")
            if brk_end_str:
                brk_end = datetime.fromisoformat(brk_end_str.replace("Z", "+00:00"))
                break_minutes += Decimal(str((brk_end - brk_start).total_seconds())) / Decimal("60")

    paid_minutes = max(total_minutes - break_minutes, Decimal("0"))
    paid_hours = paid_minutes / Decimal("60")

    # Regular / OT / DT split (8 hour threshold for OT)
    regular_hours = min(paid_hours, Decimal("8"))
    overtime_hours = max(paid_hours - Decimal("8"), Decimal("0"))
    doubletime_hours = Decimal("0")  # Not used at Cobblestone currently

    # Tips
    declared_cash_tip = _money_to_decimal(tc.get("declared_cash_tip_money"))

    return {
        "id": tc["id"],
        "team_member_id": tc.get("team_member_id", ""),
        "location_id": tc.get("location_id", ""),
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat() if end_at else None,
        "total_minutes": total_minutes,
        "break_minutes": break_minutes,
        "paid_minutes": paid_minutes,
        "regular_hours": regular_hours.quantize(Decimal("0.01")),
        "overtime_hours": overtime_hours.quantize(Decimal("0.01")),
        "doubletime_hours": doubletime_hours.quantize(Decimal("0.01")),
        "status": tc.get("status", ""),
        "declared_cash_tip": declared_cash_tip,
    }


# --- Sales / Orders ---

def get_weekly_sales(start_date, end_date):
    """Fetch completed order totals for a date range.

    Args:
        start_date: 'YYYY-MM-DD' (Monday)
        end_date: 'YYYY-MM-DD' (Sunday)

    Returns dict:
        total_sales (Decimal), total_tips (Decimal),
        by_location: {location_id: {sales, tips}}
    """
    # Convert dates to RFC 3339 timestamps in Dublin timezone
    start_rfc = f"{start_date}T00:00:00+00:00"
    # End date is inclusive, so go to end of day
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    end_rfc = f"{end_dt.strftime('%Y-%m-%d')}T00:00:00+00:00"

    body = {
        "location_ids": config.ALL_LOCATION_IDS,
        "query": {
            "filter": {
                "state_filter": {
                    "states": ["COMPLETED"]
                },
                "date_time_filter": {
                    "closed_at": {
                        "start_at": start_rfc,
                        "end_at": end_rfc,
                    }
                },
            },
            "sort": {
                "sort_field": "CLOSED_AT",
                "sort_order": "ASC",
            },
        },
        "limit": 500,
    }

    raw_orders = _paginated_post("orders/search", body, "orders")

    total_sales = Decimal("0")
    total_tips = Decimal("0")
    by_location = {}

    for order in raw_orders:
        # Filter out NO_SALE orders (total = 0, or tender type NO_SALE)
        net_amounts = order.get("net_amounts", {})
        order_total = _money_to_decimal(net_amounts.get("total_money"))

        tenders = order.get("tenders", [])
        is_no_sale = any(t.get("type") == "NO_SALE" for t in tenders)

        if is_no_sale or order_total == Decimal("0"):
            continue

        order_tip = _money_to_decimal(net_amounts.get("tip_money"))
        loc_id = order.get("location_id", "unknown")

        total_sales += order_total
        total_tips += order_tip

        if loc_id not in by_location:
            by_location[loc_id] = {"sales": Decimal("0"), "tips": Decimal("0")}
        by_location[loc_id]["sales"] += order_total
        by_location[loc_id]["tips"] += order_tip

    return {
        "total_sales": total_sales,
        "total_tips": total_tips,
        "by_location": by_location,
    }


# --- Payments (for tip details) ---

def get_weekly_payments(start_date, end_date):
    """Fetch payments for tip breakdown. Returns list of payment dicts."""
    start_rfc = f"{start_date}T00:00:00Z"
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    end_rfc = f"{end_dt.strftime('%Y-%m-%d')}T00:00:00Z"

    params = {
        "location_id": ",".join(config.ALL_LOCATION_IDS),
        "begin_time": start_rfc,
        "end_time": end_rfc,
    }

    return _paginated_get("payments", params=params, result_key="payments")


# --- Utility ---

def week_dates(year, week_number):
    """Get Monday and Sunday dates for an ISO week number.

    Returns (start_date, end_date) as 'YYYY-MM-DD' strings.
    """
    # ISO week: Monday is day 1
    jan4 = datetime(year, 1, 4)
    start_of_week1 = jan4 - timedelta(days=jan4.isoweekday() - 1)
    monday = start_of_week1 + timedelta(weeks=week_number - 1)
    sunday = monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


def current_week():
    """Get current ISO year and week number."""
    now = datetime.now()
    iso = now.isocalendar()
    return iso[0], iso[1]


# --- Booking Payment Links ---

def create_door_fee_payment_link(booking_id, act_name, event_date, redirect_url=None):
    """Create a per-booking Square-hosted payment link for the €50 door person fee.

    The booking ID is embedded in the payment note so the /webhooks/square
    endpoint can match the payment back to the booking automatically.

    Returns (url, payment_link_id) on success, or (None, None) on failure
    / misconfiguration.  Idempotent: repeating the call with the same
    booking_id returns the same link (Square deduplicates on idempotency_key).
    """
    if not config.SQUARE_ACCESS_TOKEN:
        print("[square] SQUARE_ACCESS_TOKEN not set — payment links disabled")
        return None, None
    if not config.SQUARE_LOCATION_ID:
        print("[square] SQUARE_LOCATION_ID not set — payment links disabled")
        return None, None

    body = {
        "idempotency_key": f"cobblestone-door-{booking_id}",
        "quick_pay": {
            "name": f"Door person fee — {act_name} ({event_date})",
            "price_money": {
                "amount": 5000,   # €50 in cents
                "currency": "EUR",
            },
            "location_id": config.SQUARE_LOCATION_ID,
        },
        "payment_note": f"cobblestone_booking_id:{booking_id}",
    }
    if redirect_url:
        body["checkout_options"] = {"redirect_url": redirect_url}

    try:
        resp = requests.post(
            f"{config.SQUARE_BASE_URL}/online-checkout/payment-links",
            headers=_headers(),
            json=body,
        )
        resp.raise_for_status()
        link = resp.json().get("payment_link", {})
        url = link.get("url")
        lid = link.get("id")
        print(f"[square] Created payment link {lid!r} for booking #{booking_id}")
        return url, lid
    except Exception as e:
        print(f"[square] Failed to create payment link for booking #{booking_id}: {e}")
        return None, None
