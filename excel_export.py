"""Excel export for Cobblestone Pub payroll reports.

Generates two formats:
1. "For Peter" - formatted payroll for the accountant
2. "Raw Timecards" - Square timecard data
"""

from io import BytesIO
from decimal import Decimal
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers


HEADER_FONT = Font(bold=True, color="FFFFFF", size=10, name="Arial")
HEADER_FILL = PatternFill("solid", fgColor="343A40")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
MONEY_FORMAT = '#,##0.00'
HOURS_FORMAT = '0.00'
THIN_BORDER = Border(
    left=Side(style="thin", color="D0D0D0"),
    right=Side(style="thin", color="D0D0D0"),
    top=Side(style="thin", color="D0D0D0"),
    bottom=Side(style="thin", color="D0D0D0"),
)
TOTAL_FILL = PatternFill("solid", fgColor="E9ECEF")
TOTAL_FONT = Font(bold=True, size=10, name="Arial")
BODY_FONT = Font(size=10, name="Arial")


def _apply_header(ws, row, col, value):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL
    cell.alignment = HEADER_ALIGN
    cell.border = THIN_BORDER


def _apply_body(ws, row, col, value, fmt=None):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = BODY_FONT
    cell.border = THIN_BORDER
    if fmt:
        cell.number_format = fmt
    return cell


def generate_peter_excel(week_label, payroll_data, net_sales=None):
    """Generate the 'for Peter' payroll Excel.

    Columns:
      A=(blank) B=First C=Last D=Wage E=Gross F=Hours G=Tips H=Cleaning
      I=Bonus J=Holiday Hrs K=Holiday Pay L=Total (incl. holiday pay)
      M=Category N=Upper Management O=Management P=Staff Q=Staff+M
    """
    wb = Workbook()
    ws = wb.active
    ws.title = f"{week_label} for Peter"

    headers = [
        "", "First", "Last", "Wage", "Gross", "Hours", "Tips",
        "Cleaning", "Bonus", "Holiday Hrs", "Holiday Pay", "Total",
        "Category",
        "Upper Management", "Management", "Staff", "Staff+M"
    ]

    for col, h in enumerate(headers, 1):
        _apply_header(ws, 1, col, h)

    widths = [4, 14, 18, 8, 10, 8, 8, 10, 10, 11, 11, 10, 12, 18, 14, 10, 10]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i) if i <= 26 else ""].width = w

    row = 2
    um_total = Decimal("0")
    mgmt_total = Decimal("0")
    staff_total = Decimal("0")

    for emp in payroll_data:
        wage = Decimal(str(emp["wage_rate"]))
        holiday_hrs = Decimal(str(emp.get("holiday_hours", 0) or 0))
        # Prefer the pre-computed holiday_pay from _load_week_payroll (which
        # also rolls it into total and total_for_labor). Fall back to compute
        # it here if a caller passes raw rows without that field.
        if emp.get("holiday_pay") is not None:
            holiday_pay = Decimal(str(emp["holiday_pay"]))
        else:
            holiday_pay = (holiday_hrs * wage).quantize(Decimal("0.01"))

        _apply_body(ws, row, 2, emp["given_name"])
        _apply_body(ws, row, 3, emp["family_name"])
        _apply_body(ws, row, 4, float(wage), MONEY_FORMAT)
        _apply_body(ws, row, 5, float(emp["gross"]), MONEY_FORMAT)
        _apply_body(ws, row, 6, float(emp["hours"]), HOURS_FORMAT)
        _apply_body(ws, row, 7, float(emp["tips"]), MONEY_FORMAT)
        _apply_body(ws, row, 8, float(emp["cleaning"]), MONEY_FORMAT)
        _apply_body(ws, row, 9, float(emp.get("bonus", 0)), MONEY_FORMAT)
        _apply_body(ws, row, 10, float(holiday_hrs), HOURS_FORMAT)
        _apply_body(ws, row, 11, float(holiday_pay), MONEY_FORMAT)
        # Total (col L) includes holiday pay — Peter uses this as the gross figure
        _apply_body(ws, row, 12, float(emp["total"]), MONEY_FORMAT)

        # Col M: category label; cols N-Q: per-category subtotals
        _apply_body(ws, row, 13, "UM" if emp["category"] == "Upper Management" else emp["category"])

        cat = emp["category"]
        if cat == "Upper Management":
            _apply_body(ws, row, 14, float(emp["total_for_labor"]), MONEY_FORMAT)
            um_total += emp["total_for_labor"]
        elif cat == "Management":
            _apply_body(ws, row, 15, float(emp["total_for_labor"]), MONEY_FORMAT)
            mgmt_total += emp["total_for_labor"]
        elif cat == "Staff":
            _apply_body(ws, row, 16, float(emp["total_for_labor"]), MONEY_FORMAT)
            staff_total += emp["total_for_labor"]

        row += 1

    # Totals row
    total_row = row
    for col in range(1, 18):
        cell = ws.cell(row=total_row, column=col)
        cell.fill = TOTAL_FILL
        cell.font = TOTAL_FONT
        cell.border = THIN_BORDER

    ws.cell(row=total_row, column=2, value="TOTALS").font = TOTAL_FONT

    if len(payroll_data) > 0:
        data_start = 2
        data_end = total_row - 1
        ws.cell(row=total_row, column=5,  value=f"=SUM(E{data_start}:E{data_end})").number_format = MONEY_FORMAT
        ws.cell(row=total_row, column=6,  value=f"=SUM(F{data_start}:F{data_end})").number_format = HOURS_FORMAT
        ws.cell(row=total_row, column=7,  value=f"=SUM(G{data_start}:G{data_end})").number_format = MONEY_FORMAT
        ws.cell(row=total_row, column=8,  value=f"=SUM(H{data_start}:H{data_end})").number_format = MONEY_FORMAT
        ws.cell(row=total_row, column=9,  value=f"=SUM(I{data_start}:I{data_end})").number_format = MONEY_FORMAT
        ws.cell(row=total_row, column=10, value=f"=SUM(J{data_start}:J{data_end})").number_format = HOURS_FORMAT
        ws.cell(row=total_row, column=11, value=f"=SUM(K{data_start}:K{data_end})").number_format = MONEY_FORMAT
        ws.cell(row=total_row, column=12, value=f"=SUM(L{data_start}:L{data_end})").number_format = MONEY_FORMAT

    # Category totals
    ws.cell(row=total_row, column=14, value=float(um_total)).number_format = MONEY_FORMAT
    ws.cell(row=total_row, column=15, value=float(mgmt_total)).number_format = MONEY_FORMAT
    ws.cell(row=total_row, column=16, value=float(staff_total)).number_format = MONEY_FORMAT
    ws.cell(row=total_row, column=17, value=float(mgmt_total + staff_total)).number_format = MONEY_FORMAT

    # Summary block below totals
    row = total_row + 2
    if net_sales is not None:
        ws.cell(row=row, column=2, value="Net Sales").font = TOTAL_FONT
        ws.cell(row=row, column=5, value=float(net_sales)).number_format = MONEY_FORMAT
        row += 1
        ws.cell(row=row, column=2, value="Total Labor").font = TOTAL_FONT
        ws.cell(row=row, column=5, value=float(um_total + mgmt_total + staff_total)).number_format = MONEY_FORMAT
        row += 1
        labor_total = um_total + mgmt_total + staff_total
        if net_sales > 0:
            labor_pct = float(labor_total / net_sales * 100)
            ws.cell(row=row, column=2, value="Labor %").font = TOTAL_FONT
            cell = ws.cell(row=row, column=5, value=labor_pct / 100)
            cell.number_format = '0.0%'

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def generate_raw_timecard_excel(week_label, timecard_data):
    """Generate raw timecard Excel matching Square export format.

    Args:
        week_label: e.g. "Week 15"
        timecard_data: list of dicts with keys:
            employee_id, given_name, family_name,
            regular_hours, overtime_hours, doubletime_hours, total_hours,
            regular_cost, overtime_cost, doubletime_cost, total_cost,
            transaction_tips, declared_cash_tips

    Returns BytesIO with .xlsx content.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = week_label

    headers = [
        "Employee number", "First name", "Last name",
        "Regular hours", "Overtime hours", "Doubletime hours", "Total paid hours",
        "Regular labor cost", "Overtime labor cost", "Doubletime labor cost",
        "Total labor cost", "Transaction tips", "Declared cash tips"
    ]

    for col, h in enumerate(headers, 1):
        _apply_header(ws, 1, col, h)

    widths = [16, 12, 18, 14, 14, 16, 16, 18, 18, 20, 16, 16, 18]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i) if i <= 26 else ""].width = w

    row = 2
    for emp in timecard_data:
        _apply_body(ws, row, 1, emp.get("employee_id", ""))
        _apply_body(ws, row, 2, emp["given_name"])
        _apply_body(ws, row, 3, emp["family_name"])
        _apply_body(ws, row, 4, float(emp["regular_hours"]), HOURS_FORMAT)
        _apply_body(ws, row, 5, float(emp["overtime_hours"]), HOURS_FORMAT)
        _apply_body(ws, row, 6, float(emp["doubletime_hours"]), HOURS_FORMAT)
        _apply_body(ws, row, 7, float(emp["total_hours"]), HOURS_FORMAT)

        # Format costs as EUR strings to match existing spreadsheets
        for col_idx, key in [(8, "regular_cost"), (9, "overtime_cost"),
                             (10, "doubletime_cost"), (11, "total_cost"),
                             (12, "transaction_tips"), (13, "declared_cash_tips")]:
            val = emp.get(key, Decimal("0"))
            _apply_body(ws, row, col_idx, f"EUR{float(val):.2f}")

        row += 1

    # Totals
    total_row = row
    for col in range(1, 14):
        cell = ws.cell(row=total_row, column=col)
        cell.fill = TOTAL_FILL
        cell.font = TOTAL_FONT
        cell.border = THIN_BORDER

    ws.cell(row=total_row, column=2, value="TOTALS").font = TOTAL_FONT

    if len(timecard_data) > 0:
        for col in [4, 5, 6, 7]:
            ws.cell(row=total_row, column=col, value=f"=SUM({chr(64+col)}2:{chr(64+col)}{total_row-1})").number_format = HOURS_FORMAT

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def generate_invoice_monthly_excel(period_label, invoices):
    """Monthly invoice summary for the accountant / VAT prep.

    Two sheets:
      'Invoices'  — one row per approved invoice with all fields
      'Summary'   — totals by category, by VAT rate, grand total

    Args:
        period_label: human-readable period (e.g. 'April 2026' or
            'April-May 2026' for a VAT period).
        invoices: list of approved invoice rows from db.list_invoices().

    Returns BytesIO of an .xlsx workbook.
    """
    wb = Workbook()

    # ─── Sheet 1: line items ─────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Invoices"

    title_cell = ws.cell(row=1, column=1,
                         value=f"Cobblestone Pub - Invoice Summary - {period_label}")
    title_cell.font = Font(bold=True, size=14, name="Arial")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=9)

    sub_cell = ws.cell(row=2, column=1,
                       value=f"{len(invoices)} approved invoice(s)")
    sub_cell.font = Font(italic=True, size=10, name="Arial", color="666666")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=9)

    headers = ["Date", "Supplier", "Invoice #", "Category",
               "Net", "VAT %", "VAT", "Total", "Status"]
    for col, h in enumerate(headers, start=1):
        _apply_header(ws, row=4, col=col, value=h)

    row = 5
    total_net = total_vat = total_total = Decimal("0")
    for inv in sorted(invoices, key=lambda i: (i["invoice_date"] or "", i["supplier_name"] or "")):
        _apply_body(ws, row, 1, inv["invoice_date"] or "")
        _apply_body(ws, row, 2, inv["supplier_name"] or "")
        _apply_body(ws, row, 3, inv["invoice_number"] or "")
        _apply_body(ws, row, 4, inv["category"] or "")
        _apply_body(ws, row, 5, float(inv["net_amount"] or 0), MONEY_FORMAT)
        _apply_body(ws, row, 6, float(inv["vat_rate"] or 0), '0.0"%"')
        _apply_body(ws, row, 7, float(inv["vat_amount"] or 0), MONEY_FORMAT)
        _apply_body(ws, row, 8, float(inv["total_amount"] or 0), MONEY_FORMAT)
        _apply_body(ws, row, 9, (inv["status"] or "").title())
        total_net   += Decimal(str(inv["net_amount"] or 0))
        total_vat   += Decimal(str(inv["vat_amount"] or 0))
        total_total += Decimal(str(inv["total_amount"] or 0))
        row += 1

    # Totals row
    total_row = row
    _apply_body(ws, total_row, 1, "TOTAL")
    ws.cell(row=total_row, column=1).font = TOTAL_FONT
    ws.cell(row=total_row, column=1).fill = TOTAL_FILL
    for c in range(2, 10):
        cell = ws.cell(row=total_row, column=c)
        cell.fill = TOTAL_FILL
        cell.font = TOTAL_FONT
        cell.border = THIN_BORDER
    ws.cell(row=total_row, column=5, value=float(total_net)).number_format = MONEY_FORMAT
    ws.cell(row=total_row, column=7, value=float(total_vat)).number_format = MONEY_FORMAT
    ws.cell(row=total_row, column=8, value=float(total_total)).number_format = MONEY_FORMAT

    widths = [12, 28, 14, 18, 12, 8, 12, 12, 12]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=4, column=i).column_letter].width = w

    # ─── Sheet 2: summary ────────────────────────────────────────────────────
    sm = wb.create_sheet("Summary")

    sm.cell(row=1, column=1, value=f"Summary - {period_label}").font = Font(bold=True, size=14, name="Arial")
    sm.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4)

    sm.cell(row=3, column=1, value="By Category").font = Font(bold=True, size=11, name="Arial")
    for col, h in enumerate(["Category", "Net", "VAT", "Total"], start=1):
        _apply_header(sm, row=4, col=col, value=h)

    by_cat = {}
    for inv in invoices:
        c = inv["category"] or "(uncategorised)"
        if c not in by_cat:
            by_cat[c] = {"net": Decimal("0"), "vat": Decimal("0"), "total": Decimal("0")}
        by_cat[c]["net"]   += Decimal(str(inv["net_amount"] or 0))
        by_cat[c]["vat"]   += Decimal(str(inv["vat_amount"] or 0))
        by_cat[c]["total"] += Decimal(str(inv["total_amount"] or 0))

    r = 5
    for cat, vals in sorted(by_cat.items()):
        _apply_body(sm, r, 1, cat)
        _apply_body(sm, r, 2, float(vals["net"]),   MONEY_FORMAT)
        _apply_body(sm, r, 3, float(vals["vat"]),   MONEY_FORMAT)
        _apply_body(sm, r, 4, float(vals["total"]), MONEY_FORMAT)
        r += 1
    _apply_body(sm, r, 1, "TOTAL")
    sm.cell(row=r, column=1).font = TOTAL_FONT
    sm.cell(row=r, column=1).fill = TOTAL_FILL
    for c in range(2, 5):
        sm.cell(row=r, column=c).fill = TOTAL_FILL
        sm.cell(row=r, column=c).font = TOTAL_FONT
        sm.cell(row=r, column=c).border = THIN_BORDER
    sm.cell(row=r, column=2, value=float(total_net)).number_format = MONEY_FORMAT
    sm.cell(row=r, column=3, value=float(total_vat)).number_format = MONEY_FORMAT
    sm.cell(row=r, column=4, value=float(total_total)).number_format = MONEY_FORMAT
    cat_total_row = r

    sm.cell(row=cat_total_row + 3, column=1, value="By VAT Rate").font = Font(bold=True, size=11, name="Arial")
    for col, h in enumerate(["VAT Rate", "Net", "VAT", "Total"], start=1):
        _apply_header(sm, row=cat_total_row + 4, col=col, value=h)

    by_rate = {}
    for inv in invoices:
        rate = float(inv["vat_rate"] or 0)
        if rate not in by_rate:
            by_rate[rate] = {"net": Decimal("0"), "vat": Decimal("0"), "total": Decimal("0")}
        by_rate[rate]["net"]   += Decimal(str(inv["net_amount"] or 0))
        by_rate[rate]["vat"]   += Decimal(str(inv["vat_amount"] or 0))
        by_rate[rate]["total"] += Decimal(str(inv["total_amount"] or 0))

    r = cat_total_row + 5
    for rate, vals in sorted(by_rate.items(), reverse=True):
        _apply_body(sm, r, 1, f"{rate:g}%")
        _apply_body(sm, r, 2, float(vals["net"]),   MONEY_FORMAT)
        _apply_body(sm, r, 3, float(vals["vat"]),   MONEY_FORMAT)
        _apply_body(sm, r, 4, float(vals["total"]), MONEY_FORMAT)
        r += 1

    for i, w in enumerate([20, 14, 14, 14], start=1):
        sm.column_dimensions[sm.cell(row=4, column=i).column_letter].width = w

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ─── VAT Period Export (Peter format) ────────────────────────────────────────

def generate_vat_period_excel(m1_label: str, m2_label: str,
                               m1_invoices: list, m2_invoices: list,
                               m1_sales, m2_sales) -> BytesIO:
    """Generate a bimonthly VAT summary matching the accountant (Peter) format.

    Five sheets:
      SUMMARY           — one-glance totals for both months
      {m1} VAT Collected — sales by VAT rate from Square
      {m1} VAT Paid      — approved invoices for month 1
      {m2} VAT Collected — sales by VAT rate from Square
      {m2} VAT Paid      — approved invoices for month 2

    Args:
        m1_label / m2_label: e.g. "March", "April"
        m1_invoices / m2_invoices: list of approved invoice dicts (from db.list_invoices)
        m1_sales / m2_sales: dict from square_client.get_monthly_sales_by_rate,
            or None if Square data is unavailable (leaves collected sheet blank).
    """
    GREY_HDR = "343A40"
    WHITE    = "FFFFFF"
    GREY_BG  = "E9ECEF"

    def _hdr(ws, row, col, val, bg=GREY_HDR):
        c = ws.cell(row=row, column=col, value=val)
        c.font = Font(bold=True, color=WHITE, size=10, name="Arial")
        c.fill = PatternFill("solid", fgColor=bg)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = THIN_BORDER
        return c

    def _body(ws, row, col, val, fmt=None, bold=False, align="right"):
        c = ws.cell(row=row, column=col, value=val)
        c.font = Font(bold=bold, size=10, name="Arial")
        c.alignment = Alignment(horizontal=align)
        c.border = THIN_BORDER
        if fmt:
            c.number_format = fmt
        return c

    def _total_row_ws(ws, row, ncols, label, *values, bg=GREY_BG):
        c = ws.cell(row=row, column=1, value=label)
        c.font = Font(bold=True, size=10, name="Arial")
        c.fill = PatternFill("solid", fgColor=bg)
        c.border = THIN_BORDER
        for col, val in enumerate(values, start=2):
            cell = ws.cell(row=row, column=col, value=float(val) if val is not None else None)
            cell.font = Font(bold=True, size=10, name="Arial")
            cell.fill = PatternFill("solid", fgColor=bg)
            cell.alignment = Alignment(horizontal="right")
            if val is not None:
                cell.number_format = MONEY_FORMAT
            cell.border = THIN_BORDER
        for col in range(len(values) + 2, ncols + 1):
            ws.cell(row=row, column=col).fill = PatternFill("solid", fgColor=bg)
            ws.cell(row=row, column=col).border = THIN_BORDER

    def _inv_totals(invoices):
        net = sum(Decimal(str(i["net_amount"] or 0)) for i in invoices)
        vat = sum(Decimal(str(i["vat_amount"] or 0)) for i in invoices)
        tot = sum(Decimal(str(i["total_amount"] or 0)) for i in invoices)
        return net, vat, tot

    def _sales_vat(sales):
        if not sales:
            return Decimal("0")
        return sales.get("total_tax", Decimal("0"))

    m1_net, m1_vat_paid, m1_total_paid = _inv_totals(m1_invoices)
    m2_net, m2_vat_paid, m2_total_paid = _inv_totals(m2_invoices)
    m1_vat_collected = _sales_vat(m1_sales)
    m2_vat_collected = _sales_vat(m2_sales)

    wb = Workbook()

    # ── SUMMARY ──────────────────────────────────────────────────────────────
    ws = wb.active
    ws.title = "SUMMARY"
    ws.sheet_view.showGridLines = False
    for col_letter, width in [("A", 22), ("B", 16), ("C", 22), ("D", 16)]:
        ws.column_dimensions[col_letter].width = width

    def _sum(row, col, label=None, val=None, bold=False):
        if label is not None:
            c = ws.cell(row=row, column=col, value=label)
            c.font = Font(bold=bold, size=11, name="Arial")
        if val is not None:
            c = ws.cell(row=row, column=col, value=float(val))
            c.font = Font(bold=bold, size=11, name="Arial")
            c.alignment = Alignment(horizontal="right")
            c.number_format = MONEY_FORMAT

    ws.row_dimensions[1].height = 6
    _sum(2, 1, label=f"{m1_label} VAT Paid",      bold=True)
    _sum(2, 2, val=-m1_vat_paid,                   bold=True)
    _sum(2, 3, label=f"{m2_label} VAT Paid",       bold=True)
    _sum(2, 4, val=-m2_vat_paid,                   bold=True)

    _sum(3, 1, label=f"{m1_label} VAT Collected")
    _sum(3, 2, val=m1_vat_collected)
    _sum(3, 3, label=f"{m2_label} VAT Collected")
    _sum(3, 4, val=m2_vat_collected)

    m1_net_pos = m1_vat_collected - m1_vat_paid
    m2_net_pos = m2_vat_collected - m2_vat_paid
    _sum(4, 1, label="Total",      bold=True)
    _sum(4, 2, val=m1_net_pos,     bold=True)
    _sum(4, 3, label="",           bold=False)
    _sum(4, 4, val=m2_net_pos,     bold=True)

    _sum(5, 1, label="Total owed", bold=True)
    _sum(5, 2, val=m1_net_pos + m2_net_pos, bold=True)

    # ── VAT Collected sheet ───────────────────────────────────────────────────
    def _write_collected(month_label, sales):
        ws2 = wb.create_sheet(title=f"{month_label} VAT Collected")
        ws2.sheet_view.showGridLines = False
        ws2.column_dimensions["A"].width = 22
        ws2.column_dimensions["B"].width = 16
        ws2.column_dimensions["C"].width = 16
        _hdr(ws2, 1, 1, "")
        _hdr(ws2, 1, 2, "Sales")
        _hdr(ws2, 1, 3, "Tax")

        row = 2
        total_s = Decimal("0")
        total_t = Decimal("0")
        if sales and sales.get("by_rate"):
            for key in sales["by_rate"]:
                v = sales["by_rate"][key]
                if not (v["sales"] or v["tax"]):
                    continue
                # key is either a float rate (e.g. 23.0) or "Total"
                if isinstance(key, float):
                    label_txt = f"Sales @ {key:g}%"
                else:
                    label_txt = "Sales"
                _body(ws2, row, 1, label_txt, align="left")
                _body(ws2, row, 2, float(v["sales"]), MONEY_FORMAT)
                _body(ws2, row, 3, float(v["tax"]),   MONEY_FORMAT)
                total_s += v["sales"]
                total_t += v["tax"]
                row += 1
        else:
            _body(ws2, row, 1, "Square data unavailable — enter manually", align="left")
            _body(ws2, row, 2, None)
            _body(ws2, row, 3, None)
            row += 1

        _total_row_ws(ws2, row, 3, "Total",
                      float(total_s) if sales else None,
                      float(total_t) if sales else None)

    # ── VAT Paid sheet ────────────────────────────────────────────────────────
    def _write_paid(month_label, invoices):
        ws3 = wb.create_sheet(title=f"{month_label} VAT Paid")
        ws3.sheet_view.showGridLines = False

        t = ws3.cell(row=1, column=1,
                     value=f"Cobblestone Pub - Invoice Summary - {month_label}")
        t.font = Font(bold=True, size=14, name="Arial")
        ws3.merge_cells("A1:I1")

        s = ws3.cell(row=2, column=1, value=f"{len(invoices)} approved invoice(s)")
        s.font = Font(italic=True, size=10, name="Arial", color="666666")
        ws3.merge_cells("A2:I2")

        for col, h in enumerate(["Date","Supplier","Invoice #","Category",
                                  "Net","VAT %","VAT","Total","Status"], 1):
            _hdr(ws3, 4, col, h)

        row = 5
        total_net = total_vat_amt = total_total = Decimal("0")
        for inv in sorted(invoices, key=lambda i: (i["invoice_date"] or "", i["supplier_name"] or "")):
            _body(ws3, row, 1, inv["invoice_date"] or "",        align="left")
            _body(ws3, row, 2, inv["supplier_name"] or "",       align="left")
            _body(ws3, row, 3, inv["invoice_number"] or "",      align="left")
            _body(ws3, row, 4, inv["category"] or "",            align="left")
            _body(ws3, row, 5, float(inv["net_amount"] or 0),   MONEY_FORMAT)
            _body(ws3, row, 6, float(inv["vat_rate"] or 0),     '0.0"%"')
            _body(ws3, row, 7, float(inv["vat_amount"] or 0),   MONEY_FORMAT)
            _body(ws3, row, 8, float(inv["total_amount"] or 0), MONEY_FORMAT)
            _body(ws3, row, 9, (inv["status"] or "").title(),   align="left")
            total_net     += Decimal(str(inv["net_amount"] or 0))
            total_vat_amt += Decimal(str(inv["vat_amount"] or 0))
            total_total   += Decimal(str(inv["total_amount"] or 0))
            row += 1

        _total_row_ws(ws3, row, 9, "TOTAL",
                      float(total_net), None, float(total_vat_amt), float(total_total))
        for i, w in enumerate([12, 28, 16, 20, 12, 8, 12, 12, 10], 1):
            ws3.column_dimensions[ws3.cell(row=4, column=i).column_letter].width = w

    _write_collected(m1_label, m1_sales)
    _write_paid(m1_label, m1_invoices)
    _write_collected(m2_label, m2_sales)
    _write_paid(m2_label, m2_invoices)

    buf2 = BytesIO()
    wb.save(buf2)
    buf2.seek(0)
    return buf2
