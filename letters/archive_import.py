"""
Old Archive Excel Import Utilities.
Supports importing bulk historical paper letters from Excel spreadsheets (.xlsx, .xls)
with column matching (Ref. No., Organizations, Subject, Date) and dual calendar parsing.
"""

import re
from datetime import date, datetime
from io import BytesIO
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from django.db import transaction
from django.utils import timezone

from .models import Letter, Department, Category, ActionLog
from .ethiopian_calendar import parse_ethiopian_date, ethiopian_to_gregorian


# ---------------------------------------------------------------------------
# Column Header Normalization & Matching
# ---------------------------------------------------------------------------
def _normalize_header(name: str) -> str:
    """Normalize header by lowercase and stripping punctuation/whitespace."""
    if not name:
        return ""
    clean = re.sub(r"[^a-zA-Z0-9]", "", str(name).lower())
    return clean


HEADER_MAP = {
    # Reference Number aliases
    "refno": "reference_no",
    "refnum": "reference_no",
    "referenceno": "reference_no",
    "referencenumber": "reference_no",
    "letterno": "reference_no",
    "letternumber": "reference_no",
    "ref": "reference_no",
    "fileno": "reference_no",

    # Organization / Party aliases
    "organizations": "organization",
    "organization": "organization",
    "org": "organization",
    "sender": "organization",
    "recipient": "organization",
    "senderto": "organization",
    "company": "organization",
    "party": "organization",
    "from": "organization",
    "to": "organization",
    "institution": "organization",

    # Subject aliases
    "subject": "subject",
    "title": "subject",
    "description": "subject",
    "summary": "subject",
    "topic": "subject",
    "content": "subject",

    # Date aliases
    "date": "date",
    "letterdate": "date",
    "originaldate": "date",
    "dated": "date",
    "registrationdate": "date",

    # Optional columns
    "department": "department",
    "dept": "department",
    "custodian": "department",
    "category": "category",
    "priority": "priority",
    "attentionto": "attention_to",
    "attention": "attention_to",
    "attn": "attention_to",
    "notes": "archive_notes",
    "archivenotes": "archive_notes",
    "location": "archive_notes",
    "storage": "archive_notes",
    "cabinet": "archive_notes",
    "box": "archive_notes",
    "folder": "archive_notes",
}


def _sanitize_date_string(raw: str) -> str:
    """Clean noise from date strings: internal spaces, time parts, ordinals."""
    if not raw:
        return ""
    s = str(raw).replace("\u00a0", " ").replace("\ufeff", "").strip()

    # Strip time portions like "2025-03-09 00:00:00" or "09/03/2025 14:30"
    if " " in s and re.search(r"\d{1,2}:\d{2}", s):
        parts = s.split()
        if len(parts) >= 2 and any(sep in parts[0] for sep in ["-", "/", "."]):
            s = parts[0]
    elif "T" in s and re.search(r"T\d{2}:\d{2}", s):
        s = s.split("T")[0]

    # Remove whitespace around separators: "09 / 0 3 / 2025" → "09/0 3/2025"
    s = re.sub(r"\s*([/\-.])\s*", r"\1", s)

    # Remove whitespace inside digit-only segments: "0 3" → "03"
    segments = re.split(r"([/\-.])", s)
    cleaned = []
    for seg in segments:
        if seg in ("/", "-", "."):
            cleaned.append(seg)
        elif re.fullmatch(r"[\d\s]+", seg) and any(c.isdigit() for c in seg):
            cleaned.append(re.sub(r"\s+", "", seg))
        else:
            cleaned.append(re.sub(r"\s+", " ", seg).strip())
    s = "".join(cleaned)

    # Remove ordinal suffixes: 1st, 2nd, 3rd, 15th
    s = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _parse_row_date(val, date_mode: str = "AUTO") -> date:
    """Parse cell value into a Gregorian date object."""
    if val is None or val == "":
        return timezone.now().date()

    if isinstance(val, datetime):
        val = val.date()

    if isinstance(val, date):
        if date_mode == "ETHIOPIAN":
            # Values like 2015-04-10 were parsed by Excel as year 2015, month 4, day 10
            try:
                converted = ethiopian_to_gregorian(val.year, val.month, val.day)
                if converted:
                    return converted
            except Exception:
                pass
        return val

    # Convert string — sanitize first
    date_str = _sanitize_date_string(str(val))
    if not date_str:
        return timezone.now().date()

    # If Ethiopian mode
    if date_mode == "ETHIOPIAN":
        try:
            parsed = parse_ethiopian_date(date_str)
            if parsed:
                return parsed
        except Exception:
            pass

    # Common Gregorian formats
    formats = [
        "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
        "%d-%m-%Y", "%m-%d-%Y", "%d.%m.%Y",
        "%Y/%m/%d", "%Y.%m.%d", "%d %b %Y",
        "%d %B %Y", "%b %d, %Y", "%B %d, %Y"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except (ValueError, TypeError):
            continue

    # Try dateutil if available
    try:
        from dateutil import parser
        return parser.parse(date_str).date()
    except Exception:
        pass

    # Try Ethiopian parser as fallback in AUTO mode
    if date_mode == "AUTO":
        try:
            parsed = parse_ethiopian_date(date_str)
            if parsed:
                return parsed
        except Exception:
            pass

    # If all parsing fails, return today's date
    return timezone.now().date()


# ---------------------------------------------------------------------------
# Excel Import Processor
# ---------------------------------------------------------------------------
def import_archive_letters_from_excel(
    file_obj,
    user,
    direction: str = "INCOMING",
    default_dept=None,
    default_cat=None,
    default_notes: str = "",
    date_mode: str = "AUTO",
) -> dict:
    """
    Parse an Excel file and create Letter records in bulk for the Old Archive.
    """
    result = {
        "success": True,
        "imported_count": 0,
        "skipped_count": 0,
        "errors": [],
        "created_letters": [],
    }

    try:
        workbook = openpyxl.load_workbook(file_obj, data_only=True)
    except Exception as e:
        result["success"] = False
        result["errors"].append(f"Failed to read Excel file: {str(e)}")
        return result

    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        result["success"] = False
        result["errors"].append("The uploaded Excel sheet is empty.")
        return result

    # Find header row (first row with at least 2 non-empty cells)
    header_row_idx = None
    column_mapping = {}

    for idx, row in enumerate(rows[:10]):
        non_empty = [c for c in row if c is not None and str(c).strip() != ""]
        if len(non_empty) >= 2:
            # Check if any recognized columns match
            matched = {}
            for col_idx, cell_val in enumerate(row):
                if cell_val:
                    norm = _normalize_header(cell_val)
                    if norm in HEADER_MAP:
                        matched[col_idx] = HEADER_MAP[norm]

            if len(matched) >= 2:
                header_row_idx = idx
                column_mapping = matched
                break

    # Fallback to row 0 if no header row was detected
    if header_row_idx is None:
        header_row_idx = 0
        for col_idx, cell_val in enumerate(rows[0]):
            if cell_val:
                norm = _normalize_header(cell_val)
                if norm in HEADER_MAP:
                    column_mapping[col_idx] = HEADER_MAP[norm]

    # If key columns not found, use positional fallback based on user's structure:
    # Col 0: Ref. No., Col 1: Organizations, Col 2: Subject, Col 3: Date
    if "subject" not in column_mapping.values() and len(rows[0]) >= 3:
        column_mapping = {
            0: "reference_no",
            1: "organization",
            2: "subject",
            3: "date"
        }

    # Department lookup cache
    dept_cache = {d.name.lower(): d for d in Department.objects.all()}
    cat_cache = {c.name.lower(): c for c in Category.objects.all()}

    # Pre-load existing reference numbers to skip duplicates
    existing_refs = set(
        Letter.objects.filter(reference_no__isnull=False)
        .values_list("reference_no", flat=True)
    )
    seen_refs = set()  # Track ref numbers within the current file

    letters_to_create = []
    data_rows = rows[header_row_idx + 1:]

    for row_idx, row in enumerate(data_rows, start=header_row_idx + 2):
        # Skip completely empty rows
        if not any(row):
            continue

        row_data = {}
        for col_idx, field_name in column_mapping.items():
            if col_idx < len(row):
                val = row[col_idx]
                row_data[field_name] = str(val).strip() if isinstance(val, str) else val

        ref_no = str(row_data.get("reference_no") or "").strip()
        org_val = str(row_data.get("organization") or "").strip()
        subject_val = str(row_data.get("subject") or "").strip()
        raw_date = row_data.get("date")

        # Skip row if both subject and reference number are completely missing
        if not subject_val and not ref_no and not org_val:
            result["skipped_count"] += 1
            continue

        # Skip duplicate reference numbers already in the database
        if ref_no and ref_no in existing_refs:
            result["skipped_count"] += 1
            result["errors"].append(
                f"Row {row_idx}: Skipped — Ref. No. '{ref_no}' already exists."
            )
            continue

        # Skip duplicate reference numbers within the same file
        if ref_no and ref_no in seen_refs:
            result["skipped_count"] += 1
            result["errors"].append(
                f"Row {row_idx}: Skipped — duplicate Ref. No. '{ref_no}' in file."
            )
            continue
        if ref_no:
            seen_refs.add(ref_no)

        # If subject is missing, formulate meaningful default
        if not subject_val:
            subject_val = f"Historical Record {ref_no or 'Archived Paper'}"

        # Parse date
        letter_date = _parse_row_date(raw_date, date_mode=date_mode)

        # Department resolution
        assigned_dept = default_dept
        dept_val = str(row_data.get("department") or "").strip().lower()
        if dept_val and dept_val in dept_cache:
            assigned_dept = dept_cache[dept_val]

        # Category resolution
        cat_val = default_cat
        cat_str = str(row_data.get("category") or "").strip().lower()
        if cat_str and cat_str in cat_cache:
            cat_val = cat_cache[cat_str]

        # Priority resolution
        priority_val = "NORMAL"
        pri_str = str(row_data.get("priority") or "").strip().upper()
        if pri_str in ["NORMAL", "URGENT", "CONFIDENTIAL"]:
            priority_val = pri_str

        # Attention To
        attn_val = str(row_data.get("attention_to") or "").strip()

        # Archive notes resolution
        notes_parts = []
        if default_notes:
            notes_parts.append(default_notes.strip())
        row_notes = str(row_data.get("archive_notes") or "").strip()
        if row_notes:
            notes_parts.append(row_notes)
        final_notes = " — ".join(notes_parts)

        # Instantiate Letter
        letter = Letter(
            direction=direction,
            letter_type="HARDCOPY",
            reference_no=ref_no if ref_no else None,
            subject=subject_val,
            sender=org_val if direction == Letter.INCOMING else "",
            recipient=org_val if direction == Letter.OUTGOING else "",
            attention_to=attn_val,
            date=letter_date,
            status=Letter.ARCHIVED,
            is_old_archive=True,
            priority=priority_val,
            assigned_department=assigned_dept,
            category=cat_val,
            archive_notes=final_notes,
            created_by=user,
        )
        letters_to_create.append(letter)

    if not letters_to_create:
        result["success"] = False
        result["errors"].append("No valid letter rows could be extracted from the Excel sheet.")
        return result

    # Save rows individually — one bad row won't block the rest
    for letter in letters_to_create:
        try:
            with transaction.atomic():
                letter.save()
                ActionLog.objects.create(
                    letter=letter,
                    action=f"Old archive letter imported from Excel ({letter.get_direction_display()})",
                    action_by=user,
                )
                result["created_letters"].append(letter)
                result["imported_count"] += 1
        except Exception as e:
            result["skipped_count"] += 1
            ref_display = letter.reference_no or letter.subject[:30]
            result["errors"].append(f"Row '{ref_display}': {str(e)}")

    if not result["created_letters"]:
        result["success"] = False

    return result


# ---------------------------------------------------------------------------
# Sample Template Generator
# ---------------------------------------------------------------------------
def generate_sample_archive_excel(direction: str = "INCOMING") -> BytesIO:
    """Generate a clean sample Excel workbook matching the user's columns."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Old Archive Template"

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    gold_fill = PatternFill(start_color="B45309", end_color="B45309", fill_type="solid")
    border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )

    headers = [
        "Ref. No.", "Organizations", "Subject", "Date",
        "Department", "Category", "Archive Notes"
    ]

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = gold_fill if col_idx <= 4 else header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    # Sample rows
    if direction == "INCOMING":
        sample_rows = [
            ("MOF/1998/142", "Ministry of Finance", "Budget Allocation and Grant Approval for Fiscal Year", "2015-04-10", "Finance", "Finance", "Cabinet A, Shelf 2, Box 15"),
            ("MOT/2001/089", "Ministry of Trade", "Annual Export License Renewal Notification", "2018-11-22", "Legal", "General", "Cabinet B, Shelf 1, Folder 1999"),
            ("NBE/2012/551", "National Bank of Ethiopia", "Foreign Currency Directive Compliance Notice", "2020-07-15", "Executive Office", "Legal", "Cabinet A, Shelf 3, Folder 2020"),
        ]
    else:
        sample_rows = [
            ("AE/OUT/1999/042", "Commercial Bank of Ethiopia", "Request for Letter of Credit Facility Extension", "2016-02-18", "Finance", "Finance", "Cabinet B, Shelf 4, Outgoing 2016"),
            ("AE/OUT/2005/119", "Ethiopian Revenue and Customs", "Quarterly Tax Clearance and Settlement Report", "2019-06-30", "Finance", "General", "Cabinet C, Binder 2019"),
            ("AE/OUT/2015/008", "City Administration of Addis Ababa", "Official Response Regarding Land Lease Assessment", "2021-01-14", "Legal", "Administration", "Cabinet A, Shelf 1, Folder 2021"),
        ]

    for row_idx, row_data in enumerate(sample_rows, 2):
        for col_idx, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.border = border
            if col_idx == 4:
                cell.alignment = Alignment(horizontal="center")

    col_widths = [18, 30, 45, 15, 20, 18, 35]
    for idx, width in enumerate(col_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(idx)].width = width

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output
