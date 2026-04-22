import os
from dotenv import load_dotenv

# Override ensures a .env value wins over any stale empty env var in the shell
load_dotenv(override=True)

SQUARE_ACCESS_TOKEN = os.getenv("SQUARE_ACCESS_TOKEN", "")
SQUARE_BASE_URL = "https://connect.squareup.com/v2"

# HTTP Basic Auth credentials (set in environment / Render dashboard)
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")
# Disable auth entirely when running locally (no AUTH_USERNAME set)
AUTH_ENABLED = bool(AUTH_USERNAME and AUTH_PASSWORD)

# Admin password for unlocking finalized payroll weeks (separate from login)
# If not set, defaults to the main AUTH_PASSWORD
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "") or AUTH_PASSWORD or "unlock2026"

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

# Anthropic Claude API key (for invoice extraction)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Google service account (JSON string) for Gmail + Drive access
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
# Google Drive folder ID where incoming invoice PDFs are saved
GOOGLE_DRIVE_INVOICES_FOLDER_ID = os.getenv("GOOGLE_DRIVE_INVOICES_FOLDER_ID", "")
# How often (seconds) the background thread checks the inbox (default: 30 min)
GMAIL_POLL_INTERVAL = int(os.getenv("GMAIL_POLL_INTERVAL", "1800"))

# Where uploaded invoice PDFs are stored (falls back to local if disk unset)
INVOICES_DIR = os.getenv(
    "INVOICES_DIR",
    os.path.join(os.path.dirname(os.getenv("DATABASE_PATH", ".")), "invoice_pdfs"),
)

# Where booking file uploads are stored (poster, bio, etc.)
# On Render: /var/data/booking_uploads/   Locally: ./booking_uploads/
BOOKING_UPLOADS_DIR = os.getenv(
    "BOOKING_UPLOADS_DIR",
    os.path.join(os.path.dirname(os.getenv("DATABASE_PATH", ".")), "booking_uploads"),
)

# SMTP email for booking notifications — all optional, emails skipped if absent
SMTP_HOST     = os.getenv("SMTP_HOST", "")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
# From address shown to bands (defaults to SMTP_USERNAME if not set)
BOOKING_FROM     = os.getenv("BOOKING_FROM", "")
# Reply-to address for booking emails
BOOKING_REPLY_TO = os.getenv("BOOKING_REPLY_TO", "bookings@cobblestonepub.ie")
# Public base URL used when building portal links in emails
PUBLIC_BASE_URL  = os.getenv("PUBLIC_BASE_URL", "https://cobblestone-pub.onrender.com")

# Seed suppliers - based on the March 2026 invoices folder.
# Format: (name, default_vat_rate %, default_category)
DEFAULT_SUPPLIERS = [
    # Drinks (23% VAT)
    ("Diageo", 23, "Drinks - Spirits/Beer"),
    ("Four Provinces", 23, "Drinks - Beer"),
    ("9 White Deer Brewery", 23, "Drinks - Beer"),
    ("JC Kenny", 23, "Drinks"),
    ("Tindal Wines", 23, "Drinks - Wine"),
    ("Bulmers", 23, "Drinks - Cider"),
    ("Fierce Mild", 23, "Drinks - Beer"),
    ("Noreast", 23, "Drinks"),
    # Food & grocery (mixed VAT)
    ("BWG", 13.5, "Food"),
    ("BWG Foods", 13.5, "Food"),
    ("Musgrave", 13.5, "Food"),
    ("Fresh", 13.5, "Food"),
    ("Lidl", 13.5, "Food"),
    ("Tesco", 13.5, "Food"),
    ("Gala", 13.5, "Food"),
    ("Kitchen Sink", 13.5, "Food"),
    ("ANTA Food", 13.5, "Food"),
    ("Newtown Coffee", 13.5, "Food - Coffee"),
    # Services & supplies (23% VAT)
    ("JS Cleaning", 23, "Cleaning"),
    ("Screw Fix", 23, "Supplies - Hardware"),
    ("Eir", 23, "Utilities - Telecoms"),
    ("Adobe", 23, "Software/Subscriptions"),
    ("Eva Carroll", 23, "Professional Services"),
    ("JJ Mahon", 23, "Professional Services"),
    ("SKMC", 23, "Professional Services"),
    ("FADA", 23, "Services"),
    ("Sureguard", 23, "Services - Security"),
    ("WristbandsIreland", 23, "Supplies"),
    ("City Cycle", 23, "Transport"),
    ("Go Dublin", 23, "Transport"),
    ("Easons", 23, "Supplies"),
    ("TK Max", 23, "Supplies"),
    ("Jameson", 23, "Drinks - Spirits"),
    ("Ispini", 23, "Merchandise/Supplies"),
]

# Invoice categories (pre-populated dropdown on bookkeeping page)
INVOICE_CATEGORIES = [
    "Drinks - Beer",
    "Drinks - Wine",
    "Drinks - Spirits",
    "Drinks - Spirits/Beer",
    "Drinks - Cider",
    "Drinks",
    "Food",
    "Food - Coffee",
    "Cleaning",
    "Utilities - Electricity",
    "Utilities - Gas",
    "Utilities - Telecoms",
    "Utilities - Water",
    "Supplies",
    "Supplies - Hardware",
    "Repairs & Maintenance",
    "Professional Services",
    "Software/Subscriptions",
    "Marketing",
    "Transport",
    "Rent",
    "Insurance",
    "Bank Charges",
    "Merchandise/Supplies",
    "Services",
    "Services - Security",
    "Other",
]

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
# These act as the baseline if no weekly override is set
DEFAULT_CLEANING = {
    "TMUabsLvWiJhkG2M": 85,   # Nheaca Smyth
    "TMkRH2KDKOoI8Vac": 350,  # Muhammed Naeem
}

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
