import os
from dotenv import load_dotenv

load_dotenv()

SQUARE_ACCESS_TOKEN = os.getenv("SQUARE_ACCESS_TOKEN", "")
SQUARE_BASE_URL = "https://connect.squareup.com/v2"

# HTTP Basic Auth credentials (set in environment / Render dashboard)
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")
# Disable auth entirely when running locally (no AUTH_USERNAME set)
AUTH_ENABLED = bool(AUTH_USERNAME and AUTH_PASSWORD)

LOCATION_IDS = {
    "back_room": "LVTMD7JYHNV9E",
    "main_bar": "L72Q03M0KGGFR",
    "outside": "LDMS9S19E3ZJ6",
}
ALL_LOCATION_IDS = ["LVTMD7JYHNV9E", "L72Q03M0KGGFR", "LDMS9S19E3ZJ6"]

DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    os.path.join(os.path.dirname(__file__), "cobblestone.db"),
)
TIMEZONE = "Europe/Dublin"

# Staff category defaults (Square team_member_id -> category)
# These get seeded into the database on first run
DEFAULT_CATEGORIES = {
    "TMRx8BCSob0MylD1": ("Thomas", "Mulligan", "Upper Management"),
    "TMUy3iTuSS2MB-5a": ("Soraya", "McMahon", "Upper Management"),
    "TMKsMrGAzkB38HOr": ("Tomas", "Mulligan", "Upper Management"),
    "TMiZR5Tjbhghgv2x": ("Camille", "Masson-Durcudoy", "Management"),
    "TMUabsLvWiJhkG2M": ("Nheaca", "Smyth", "Management"),
    "TMIosdi9OKD96Fdv": ("Carlos", "Soto", "Staff"),
    "TMKLeYtg9NdDlRxR": ("Will", "MacInnes", "Staff"),
    "TMLkmwoaF0SpT_Ky": ("Eylem", "Kopar", "Staff"),
    "TMOSr40ZlxLCDBM-": ("Padhraig", "O'Maolagain", "Staff"),
    "TMicxOzWvOaz6LaH": ("Oonagh", "Flynn", "Staff"),
    "TMkRH2KDKOoI8Vac": ("Muhammed", "Naeem", "Staff"),
    "TMq95VZ2LL_CANC4": ("Aaron", "Nolan", "Staff"),
    "TMy5slIWdUHKRF3e": ("Fiachra", "Mulligan", "Staff"),
}

# Default cleaning allowances (team_member_id -> weekly EUR amount)
# Set to 0 for employees without cleaning allowance
DEFAULT_CLEANING = {}

# Default salary info (team_member_id -> (weekly_salary, pay_type))
# From existing "for Peter" payroll sheets
DEFAULT_SALARIES = {
    "TMRx8BCSob0MylD1": (989.22, "salaried"),   # Thomas Mulligan
    "TMUy3iTuSS2MB-5a": (400.00, "salaried"),    # Soraya McMahon
    "TMKsMrGAzkB38HOr": (750.00, "salaried"),     # Tomas Mulligan
    "TMiZR5Tjbhghgv2x": (850.00, "salaried"),    # Camille Masson-Durcudoy
    "TMUabsLvWiJhkG2M": (750.00, "salaried"),    # Nheaca Smyth (750 salary + 85 cleaning)
    "TMIosdi9OKD96Fdv": (0, "hourly"),            # Carlos Soto
    "TMKLeYtg9NdDlRxR": (0, "hourly"),            # Will MacInnes
    "TMLkmwoaF0SpT_Ky": (0, "hourly"),            # Eylem Kopar
    "TMOSr40ZlxLCDBM-": (0, "hourly"),            # Padhraig O'Maolagain
    "TMicxOzWvOaz6LaH": (0, "hourly"),            # Oonagh Flynn
    "TMkRH2KDKOoI8Vac": (0, "hourly"),            # Muhammed Naeem
    "TMq95VZ2LL_CANC4": (0, "hourly"),            # Aaron Nolan
    "TMy5slIWdUHKRF3e": (0, "hourly"),            # Fiachra Mulligan
}
