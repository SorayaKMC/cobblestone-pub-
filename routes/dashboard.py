"""Cobblestone dashboard - assembles all data for the Weekly Performance Dashboard."""

from flask import Blueprint, render_template, request, jsonify
from decimal import Decimal
from datetime import datetime, timedelta, date
import json
import square_client
import db
import config

bp = Blueprint("dashboard", __name__)

# Location IDs
BACK_ROOM = "LVTMD7JYHNV9E"
MAIN_BAR = "L72Q03M0KGGFR"
OUTSIDE = "LDMS9S19E3ZJ6"

# VAT rate (Irish standard rate on hospitality)
VAT_RATE = Decimal("1.23")
VAT_PCT = Decimal("0.23")

# T-shirt catalog items in Square - only the Cobblestone T-Shirt
# (Ispini Touched and Six Counties excluded per user request)
# name -> (item_id, variation_id, default_price_eur)
TSHIRT_ITEMS = {
    "Cobblestone T-Shirt Tee": ("LA2QN4K476BNS5FFK2WASUS6", "OI7FSQ7OJUBQISCSXRYUMUS6", 20),
}

# Set of all t-shirt item IDs for filtering order line items
TSHIRT_ITEM_IDS = {v[0] for v in TSHIRT_ITEMS.values()}
TSHIRT_VARIATION_IDS = {v[1] for v in TSHIRT_ITEMS.values()}

# Historical 2026 payroll for weeks where Square timecard data isn't complete
# (prior to Square timecard rollout)
HISTORICAL_PAYROLL_2026 = {
    1:  {"total": 7084.00, "um": 1940.00, "ms": 5144.00},
    2:  {"total": 8052.62, "um": 1940.00, "ms": 6112.62},
    3:  {"total": 6597.87, "um": 1940.00, "ms": 4657.87},
    4:  {"total": 7154.99, "um": 1940.00, "ms": 5214.99},
    5:  {"total": 8173.89, "um": 1940.00, "ms": 6233.89},
    6:  {"total": 8093.13, "um": 1940.00, "ms": 6153.13},
    7:  {"total": 6682.90, "um": 2023.00, "ms": 4659.90},
    8:  {"total": 6289.02, "um": 2022.95, "ms": 4266.07},
    9:  {"total": 6907.12, "um": 2022.95, "ms": 4884.17},
    10: {"total": 6815.13, "um": 2039.22, "ms": 4775.91},
    11: {"total": 7567.65, "um": 2139.22, "ms": 5428.43},
    12: {"total": 8405.43, "um": 2139.22, "ms": 6266.21},
    13: {"total": 7274.42, "um": 2139.22, "ms": 5135.20},
    14: {"total": 7485.53, "um": 2139.22, "ms": 5346.31},
}

# Confirmed input VAT per month (from accountant's workings)
# Month -> confirmed input VAT EUR. Unset = pending.
CONFIRMED_INPUT_VAT_2026 = {
    1: 9931,
    2: 8513,
    3: 11315,
}


def _week_dates_label(year, week):
    """Human-readable date range for a week (e.g. 'Jan 5-11')."""
    start, end = square_client.week_dates(year, week)
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    if start_dt.month == end_dt.month:
        return f"{start_dt.strftime('%b')} {start_dt.day}-{end_dt.day}"
    return f"{start_dt.strftime('%b')} {start_dt.day}-{end_dt.strftime('%b')} {end_dt.day}"


def _fetch_orders(start_date, end_date):
    """Fetch all completed orders for a date range. Returns raw orders list."""
    start_rfc = f"{start_date}T00:00:00+00:00"
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    end_rfc = f"{end_dt.strftime('%Y-%m-%d')}T00:00:00+00:00"

    body = {
        "location_ids": config.ALL_LOCATION_IDS,
        "query": {
            "filter": {
                "state_filter": {"states": ["COMPLETED"]},
                "date_time_filter": {
                    "closed_at": {"start_at": start_rfc, "end_at": end_rfc}
                },
            },
            "sort": {"sort_field": "CLOSED_AT", "sort_order": "ASC"},
        },
        "limit": 500,
    }
    return square_client._paginated_post("orders/search", body, "orders")


def _get_week_sales_with_daily(year, week):
    """Pull a week's sales from Square with daily breakdown, location split, and t-shirt units.

    Returns dict: total (ex-VAT), by_location, daily (Mon-Sun), tshirt_units, tshirt_revenue
    """
    cache_key = f"week_sales_v3_{year}_W{week:02d}"

    current_year, current_week = square_client.current_week()
    is_current = (year == current_year and week == current_week)
    is_future = (year > current_year) or (year == current_year and week > current_week)

    if is_future:
        return None

    # Completed weeks: cache forever. Current week: cache for 5 minutes.
    cached, synced_at = db.get_cache(cache_key)
    if cached:
        if not is_current:
            return cached
        # Current week - check if cache is fresh enough (5 min)
        if synced_at:
            try:
                synced_dt = datetime.fromisoformat(synced_at)
                if (datetime.now() - synced_dt).total_seconds() < 300:
                    return cached
            except Exception:
                pass

    start_date, end_date = square_client.week_dates(year, week)

    try:
        raw_orders = _fetch_orders(start_date, end_date)

        total = Decimal("0")
        by_location = {BACK_ROOM: Decimal("0"), MAIN_BAR: Decimal("0"), OUTSIDE: Decimal("0")}
        daily = [Decimal("0")] * 7
        tshirt_units = 0
        tshirt_revenue = Decimal("0")

        monday = datetime.strptime(start_date, "%Y-%m-%d").date()

        for order in raw_orders:
            net_amounts = order.get("net_amounts", {})
            gross = square_client._money_to_decimal(net_amounts.get("total_money"))
            order_total_net = gross / VAT_RATE

            tenders = order.get("tenders", [])
            is_no_sale = any(t.get("type") == "NO_SALE" for t in tenders)
            if is_no_sale or gross == Decimal("0"):
                continue

            loc_id = order.get("location_id", "")
            if loc_id in by_location:
                by_location[loc_id] += order_total_net
            total += order_total_net

            closed_at = order.get("closed_at")
            if closed_at:
                closed_dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00")).date()
                day_idx = (closed_dt - monday).days
                if 0 <= day_idx <= 6:
                    daily[day_idx] += order_total_net

            # Count t-shirt line items
            for li in order.get("line_items", []):
                catalog_obj_id = li.get("catalog_object_id", "")
                if catalog_obj_id in TSHIRT_VARIATION_IDS:
                    qty = int(li.get("quantity", "0") or 0)
                    tshirt_units += qty
                    li_gross = square_client._money_to_decimal(li.get("total_money"))
                    tshirt_revenue += li_gross  # keep as gross for revenue display

        result = {
            "total": float(total),
            "by_location": {k: float(v) for k, v in by_location.items()},
            "daily": [float(d) for d in daily],
            "tshirt_units": tshirt_units,
            "tshirt_revenue": float(tshirt_revenue),
        }

        # Always cache (current week gets short TTL via lookup logic above)
        if total > 0:
            db.set_cache(cache_key, result)

        return result

    except Exception as e:
        print(f"Error fetching week {year}W{week}: {e}")
        return None


def _get_week_payroll(year, week):
    """Build payroll summary for a week.

    Uses Square timecards for current/recent weeks. Falls back to historical data
    for 2026 weeks prior to Square timecard rollout.
    """
    cache_key = f"week_payroll_{year}_W{week:02d}"
    current_year, current_week = square_client.current_week()
    is_current = (year == current_year and week == current_week)

    cached, synced_at = db.get_cache(cache_key)
    if cached:
        if not is_current:
            return cached
        if synced_at:
            try:
                synced_dt = datetime.fromisoformat(synced_at)
                if (datetime.now() - synced_dt).total_seconds() < 300:
                    return cached
            except Exception:
                pass

    start_date, end_date = square_client.week_dates(year, week)

    try:
        timecards = square_client.get_timecards(start_date, end_date)
        team_members = square_client.get_team_members()
        categories = db.get_employee_categories()

        members_by_id = {m["id"]: m for m in team_members}
        cats_by_id = {r["team_member_id"]: r for r in categories}

        emp_hours = {}
        for tc in timecards:
            tm_id = tc["team_member_id"]
            if tm_id not in emp_hours:
                emp_hours[tm_id] = Decimal("0")
            emp_hours[tm_id] += tc["regular_hours"] + tc["overtime_hours"] + tc["doubletime_hours"]

        # Include salaried employees who don't have timecards
        for cat_row in categories:
            tm_id = cat_row["team_member_id"]
            if tm_id not in emp_hours and cat_row["pay_type"] == "salaried" and cat_row["weekly_salary"] > 0:
                emp_hours[tm_id] = Decimal("0")

        um_total = mgmt_total = staff_total = Decimal("0")

        for tm_id, hours in emp_hours.items():
            cat_row = cats_by_id.get(tm_id)
            if not cat_row:
                continue

            member = members_by_id.get(tm_id, {})
            pay_type = cat_row["pay_type"]
            weekly_salary = Decimal(str(cat_row["weekly_salary"]))
            cleaning = Decimal(str(cat_row["cleaning_amount"]))
            wage_rate = member.get("hourly_rate", Decimal("0"))

            if pay_type == "salaried" and weekly_salary > 0:
                gross = weekly_salary
            else:
                gross = hours * wage_rate

            labor = gross + cleaning

            if cat_row["category"] == "Upper Management":
                um_total += labor
            elif cat_row["category"] == "Management":
                mgmt_total += labor
            elif cat_row["category"] == "Staff":
                staff_total += labor

        result = {
            "total": float(um_total + mgmt_total + staff_total),
            "um": float(um_total),
            "ms": float(mgmt_total + staff_total),
        }

        # Fall back to historical if Square timecards missing hourly staff
        if year == 2026 and week in HISTORICAL_PAYROLL_2026 and result["ms"] < 3000:
            result = HISTORICAL_PAYROLL_2026[week]

        db.set_cache(cache_key, result)

        return result

    except Exception as e:
        print(f"Error computing payroll for week {year}W{week}: {e}")
        if year == 2026 and week in HISTORICAL_PAYROLL_2026:
            return HISTORICAL_PAYROLL_2026[week]
        return {"total": 0, "um": 0, "ms": 0}


def _get_week_timecard_hours_by_day(year, week):
    """Hours by day for specific week. Returns list of {d, h, s}."""
    cache_key = f"timecard_hours_by_day_{year}_W{week:02d}"
    current_year, current_week = square_client.current_week()
    is_current = (year == current_year and week == current_week)

    cached, synced_at = db.get_cache(cache_key)
    if cached:
        if not is_current:
            return cached
        if synced_at:
            try:
                synced_dt = datetime.fromisoformat(synced_at)
                if (datetime.now() - synced_dt).total_seconds() < 300:
                    return cached
            except Exception:
                pass

    try:
        start_date, end_date = square_client.week_dates(year, week)
        timecards = square_client.get_timecards(start_date, end_date)

        monday = datetime.strptime(start_date, "%Y-%m-%d").date()
        hours_by_day = [Decimal("0")] * 7

        for tc in timecards:
            if tc.get("start_at"):
                start_dt = datetime.fromisoformat(tc["start_at"].replace("Z", "+00:00")).date()
                day_idx = (start_dt - monday).days
                if 0 <= day_idx <= 6:
                    hours = tc["regular_hours"] + tc["overtime_hours"] + tc["doubletime_hours"]
                    hours_by_day[day_idx] += hours

        week_data = _get_week_sales_with_daily(year, week)
        daily_sales = week_data["daily"] if week_data else [0] * 7

        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        result = [
            {"d": days[i], "h": float(hours_by_day[i]), "s": daily_sales[i]}
            for i in range(7)
        ]
        db.set_cache(cache_key, result)
        return result
    except Exception as e:
        print(f"Error getting hours/day for {year}W{week}: {e}")
        return []


def _compute_vat(year):
    """Auto-calculate VAT periods from live Square sales.

    Cached for 1 hour. Uses weekly sales cache to compute monthly totals.
    """
    cache_key = f"vat_periods_{year}"
    cached, synced_at = db.get_cache(cache_key)
    if cached and synced_at:
        try:
            synced_dt = datetime.fromisoformat(synced_at)
            if (datetime.now() - synced_dt).total_seconds() < 3600:
                return cached
        except Exception:
            pass
    period_months = [
        (1, 2, "MAR 15"),
        (3, 4, "MAY 15"),
        (5, 6, "JUL 15"),
        (7, 8, "SEP 15"),
        (9, 10, "NOV 15"),
        (11, 12, "JAN 15"),
    ]
    month_names = ["", "January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]

    today = date.today()
    current_month = today.month if today.year == year else 12

    vat_periods = []

    for m1, m2, due in period_months:
        # Only show the first two relevant periods
        if len(vat_periods) >= 2:
            break

        if m1 > current_month:
            break  # Future period

        # Pull sales for each month
        output_list = []
        total_output = Decimal("0")

        for m in (m1, m2):
            if m > current_month:
                output_list.append({
                    "label": f"{month_names[m]} VAT on sales",
                    "amount": 0,
                })
                continue

            # Get net sales for the month
            first_day = date(year, m, 1)
            if m == 12:
                last_day = date(year, 12, 31)
            else:
                last_day = date(year, m + 1, 1) - timedelta(days=1)

            try:
                raw = _fetch_orders(first_day.strftime("%Y-%m-%d"), last_day.strftime("%Y-%m-%d"))
                month_net = Decimal("0")
                for order in raw:
                    net_amounts = order.get("net_amounts", {})
                    gross = square_client._money_to_decimal(net_amounts.get("total_money"))
                    tenders = order.get("tenders", [])
                    is_no_sale = any(t.get("type") == "NO_SALE" for t in tenders)
                    if is_no_sale or gross == Decimal("0"):
                        continue
                    month_net += gross / VAT_RATE
                month_output = (month_net * VAT_PCT).quantize(Decimal("1"))
            except Exception as e:
                print(f"Error computing VAT for month {m}: {e}")
                month_output = Decimal("0")

            output_list.append({
                "label": f"{month_names[m]} VAT on sales",
                "amount": int(month_output),
            })
            total_output += month_output

        # Input VAT (from confirmed data)
        input_list = []
        total_input = Decimal("0")
        for m in (m1, m2):
            confirmed = CONFIRMED_INPUT_VAT_2026.get(m)
            if confirmed is not None:
                input_list.append({
                    "label": f"{month_names[m]} input VAT",
                    "amount": confirmed,
                    "confirmed": True,
                })
                total_input += Decimal(str(confirmed))
            else:
                input_list.append({
                    "label": f"{month_names[m]} input VAT",
                    "amount": 0,
                    "confirmed": False,
                })

        # Period status
        is_complete = m2 <= current_month and all(CONFIRMED_INPUT_VAT_2026.get(m) is not None for m in (m1, m2))
        status = "due" if is_complete else "pending"

        net_due = int(total_output - total_input)

        title_months = f"{month_names[m1]} + {month_names[m2]}"
        period_label = f"{month_names[m1]} 1 – {month_names[m2]} {(date(year, m2+1, 1) - timedelta(days=1)).day if m2 < 12 else 31}, {year}"

        note = None
        if not is_complete:
            if m2 > current_month:
                note = f"Output VAT live from Square. {month_names[m2]} input pending from accountant."
            else:
                pending_months = [month_names[m] for m in (m1, m2) if CONFIRMED_INPUT_VAT_2026.get(m) is None]
                note = f"Output VAT live from Square. Pending input VAT: {', '.join(pending_months)}."
        else:
            note = "Output VAT live from Square. Input VAT confirmed by accountant."

        vat_periods.append({
            "title": f"Period {(m1+1)//2} — {title_months}",
            "period": period_label,
            "status": status,
            "due": due,
            "output": output_list,
            "total_output": int(total_output),
            "input": input_list,
            "net_label": "Net VAT due" if status == "due" else "Running net VAT liability",
            "net_due": net_due,
            "note": note,
        })

    db.set_cache(cache_key, vat_periods)
    return vat_periods


def _cache_coverage(current_year, current_week):
    """Return how many weeks of the current year have sales data cached."""
    cached = 0
    for week in range(2, current_week + 1):
        key = f"week_sales_v3_{current_year}_W{week:02d}"
        data, _ = db.get_cache(key)
        if data:
            cached += 1
    return cached


@bp.route("/dashboard")
def dashboard_page():
    current_year, current_week = square_client.current_week()

    # If cache is mostly cold, show a loading page rather than timing out.
    # Warmup runs in background at app startup - just needs a few minutes.
    expected_weeks = current_week - 1  # W02..current_week
    cached = _cache_coverage(current_year, current_week)
    if expected_weeks > 0 and cached < max(1, expected_weeks - 2):
        # Less than ~90% cached - show loading page
        from flask import render_template_string
        pct = int(cached / expected_weeks * 100) if expected_weeks > 0 else 0
        return render_template_string("""
            {% extends "base.html" %}
            {% block title %}Loading Dashboard...{% endblock %}
            {% block page_title %}Dashboard{% endblock %}
            {% block content %}
            <meta http-equiv="refresh" content="15">
            <div class="card">
                <div class="card-body text-center py-5">
                    <div class="spinner-border text-primary mb-3" role="status"></div>
                    <h4>Preparing your dashboard...</h4>
                    <p class="text-muted">
                        First-time data load from Square. This takes 2-3 minutes.
                        <br>Page auto-refreshes every 15 seconds.
                    </p>
                    <div class="progress mt-4" style="height:8px;max-width:400px;margin:0 auto">
                        <div class="progress-bar bg-primary" style="width:{{ pct }}%"></div>
                    </div>
                    <small class="text-muted mt-2 d-block">{{ cached }} of {{ total }} weeks cached ({{ pct }}%)</small>
                    <hr>
                    <p class="text-muted small mb-0">
                        While you wait, other pages work fine:
                        <a href="/payroll">Payroll</a> ·
                        <a href="/pto">PTO</a> ·
                        <a href="/settings">Settings</a>
                    </p>
                </div>
            </div>
            {% endblock %}
        """, cached=cached, total=expected_weeks, pct=pct)

    wks = []
    daily = {}
    bb = {}
    out = {}
    payroll_data = []
    tshirt_weekly = []

    # Iterate W02 through current week
    for week in range(2, current_week + 1):
        wk_label = f"W{week:02d}"
        sales = _get_week_sales_with_daily(current_year, week)

        if not sales or sales["total"] == 0:
            continue

        # Get 2025 same week for comparison
        sales_2025 = _get_week_sales_with_daily(current_year - 1, week)
        n25 = round(sales_2025["total"]) if sales_2025 else 0

        wks.append({
            "wk": wk_label,
            "dates": _week_dates_label(current_year, week),
            "n26": round(sales["total"]),
            "n25": n25,
            "pay": 0,
        })

        daily[wk_label] = [round(d) for d in sales["daily"]]

        br_amt = round(sales["by_location"].get(BACK_ROOM, 0))
        out_amt = round(sales["by_location"].get(OUTSIDE, 0))
        if br_amt > 0:
            bb[wk_label] = br_amt
        if out_amt > 0:
            out[wk_label] = out_amt

        payroll = _get_week_payroll(current_year, week)
        payroll_data.append({
            "wk": wk_label,
            "total": round(payroll["total"], 2),
            "um": round(payroll["um"], 2),
            "ms": round(payroll["ms"], 2),
        })
        wks[-1]["pay"] = round(payroll["total"], 2)

        tshirt_weekly.append(sales.get("tshirt_units", 0))

    hrs = _get_week_timecard_hours_by_day(current_year, current_week)
    if not hrs:
        hrs = [{"d": d, "h": 0, "s": 0} for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]]

    # T-shirt totals (revenue from cached weekly data)
    tshirt_total_units = sum(tshirt_weekly)
    tshirt_total_revenue = round(tshirt_total_units * 20)  # €20/unit average

    # Compute VAT periods live
    try:
        vat_periods = _compute_vat(current_year)
    except Exception as e:
        print(f"VAT computation failed: {e}")
        vat_periods = []

    current_week_label = f"W{current_week:02d}"
    start, end = square_client.week_dates(current_year, current_week)
    current_week_end = datetime.strptime(end, "%Y-%m-%d").strftime("%b %-d, %Y")
    current_week_dates = _week_dates_label(current_year, current_week)

    # Is the current week complete? (i.e. past Sunday 23:59 in Dublin timezone)
    # If not, YoY uplift should exclude it so we compare only completed weeks.
    try:
        try:
            from zoneinfo import ZoneInfo
            now_dublin = datetime.now(ZoneInfo("Europe/Dublin"))
        except Exception:
            now_dublin = datetime.now()
        week_end_dt = datetime.strptime(end, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=now_dublin.tzinfo
        )
        current_week_complete = now_dublin > week_end_dt
    except Exception:
        current_week_complete = False

    # Last completed week label - shown in the uplift KPI
    last_complete_week = current_week if current_week_complete else current_week - 1
    last_complete_week_label = f"W{last_complete_week:02d}"

    return render_template("dashboard.html",
        wks_json=json.dumps(wks),
        daily_json=json.dumps(daily),
        bb_json=json.dumps(bb),
        out_json=json.dumps(out),
        merch_json=json.dumps(tshirt_weekly),
        payroll_json=json.dumps(payroll_data),
        hrs_json=json.dumps(hrs),
        vat_json=json.dumps(vat_periods),
        tshirt_price=20,
        tshirt_total_units=tshirt_total_units,
        tshirt_total_revenue=tshirt_total_revenue,
        current_week_label=current_week_label,
        current_week_end=current_week_end,
        current_week_dates=current_week_dates,
        current_week_complete=current_week_complete,
        last_complete_week_label=last_complete_week_label,
    )


@bp.route("/api/dashboard/trend")
def dashboard_trend():
    return jsonify([])
