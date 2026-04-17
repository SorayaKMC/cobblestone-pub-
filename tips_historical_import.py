"""One-time importer for historical tips from the Tips sheet 2026.xlsx.

Reads tips_historical_data.json (bundled with the app) and populates the
weekly_tips table. Weeks 8-15 of 2026.
"""

import json
import os
import db

HISTORICAL_JSON = os.path.join(os.path.dirname(__file__), "tips_historical_data.json")


def load_tips_data():
    with open(HISTORICAL_JSON) as f:
        return json.load(f)


def run_import():
    """Import all historical tips. Safe to run multiple times (uses UPSERT)."""
    data = load_tips_data()
    total_records = 0
    weeks_imported = 0
    for iso_week, tips_by_id in data.get("tips_by_week", {}).items():
        if not tips_by_id:
            continue
        db.bulk_set_weekly_tips(iso_week, tips_by_id)
        total_records += len(tips_by_id)
        weeks_imported += 1
    return {"weeks": weeks_imported, "records": total_records}
