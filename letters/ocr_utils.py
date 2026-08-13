import re
import io
import os
import logging
from datetime import datetime
from PIL import Image, ImageOps, ImageEnhance

logger = logging.getLogger(__name__)

# PDF Extraction
try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

# EasyOCR (primary engine - deep learning based, far more accurate)
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False

# Tesseract (fallback engine)
try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False

# Lazy-initialize EasyOCR reader
_easyocr_reader = None


def _get_easyocr_reader():
    """Lazy singleton for EasyOCR reader to avoid re-initializing on every request."""
    global _easyocr_reader
    if _easyocr_reader is None and EASYOCR_AVAILABLE:
        try:
            _easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        except Exception as e:
            logger.warning(f"Failed to initialize EasyOCR reader: {e}")
    return _easyocr_reader


def extract_text_from_file(file_obj, filename=""):
    """
    Extracts raw text from an uploaded file object (PDF or Image).
    Uses EasyOCR (primary) with Tesseract fallback for image-based OCR.
    For digital PDFs, uses pypdf text extraction first, falling back to OCR for scanned pages.
    Returns (raw_text, error_message) tuple.
    """
    ext = os.path.splitext(filename)[1].lower() if filename else ""
    raw_text = ""
    error_msg = None

    # ── Handle PDF files ──────────────────────────────────────────────
    if ext == ".pdf" or (hasattr(file_obj, 'content_type') and file_obj.content_type == "application/pdf"):
        if not PYPDF_AVAILABLE:
            return "", "pypdf library is not installed on the server."
        try:
            file_obj.seek(0)
            reader = pypdf.PdfReader(file_obj)
            extracted_pages = []
            for page in reader.pages:
                txt = page.extract_text()
                if txt:
                    extracted_pages.append(txt)
            raw_text = "\n\n".join(extracted_pages).strip()

            # If PDF is a scanned image (no text layer), fall back to OCR on embedded images
            if len(raw_text) < 20:
                ocr_pages = []
                file_obj.seek(0)
                reader = pypdf.PdfReader(file_obj)
                for page in reader.pages:
                    for img_obj in page.images:
                        try:
                            img = img_obj.image
                            ocr_txt = _perform_ocr_on_image(img)
                            if ocr_txt:
                                ocr_pages.append(ocr_txt)
                        except Exception:
                            pass
                if ocr_pages:
                    raw_text = "\n\n".join(ocr_pages).strip()

        except Exception as e:
            error_msg = f"Failed to extract PDF text: {str(e)}"

    # ── Handle Image files ────────────────────────────────────────────
    elif ext in [".jpg", ".jpeg", ".png", ".webp", ".tiff", ".bmp"] or (hasattr(file_obj, 'content_type') and file_obj.content_type.startswith("image/")):
        try:
            file_obj.seek(0)
            img = Image.open(file_obj)
            img = ImageOps.exif_transpose(img)
            raw_text = _perform_ocr_on_image(img)
            if not raw_text:
                error_msg = "OCR could not extract text from this image. Ensure the document is clear and well-lit."
        except Exception as e:
            error_msg = f"Failed to process image file: {str(e)}"
    else:
        error_msg = f"Unsupported file format '{ext}'. Please upload a PDF or Image (PNG, JPG, WEBP)."

    return raw_text, error_msg


def _preprocess_image(pil_image):
    """Preprocesses PIL Image for optimal OCR contrast and DPI scaling."""
    if pil_image.mode in ("RGBA", "P"):
        pil_image = pil_image.convert("RGB")

    w, h = pil_image.size
    if w < 2000 and w > 0:
        scale = 2000.0 / float(w)
        new_w, new_h = int(w * scale), int(h * scale)
        pil_image = pil_image.resize((new_w, new_h), getattr(Image, 'Resampling', Image).LANCZOS)

    pil_image = ImageOps.autocontrast(pil_image)
    enhancer = ImageEnhance.Contrast(pil_image)
    pil_image = enhancer.enhance(1.4)
    enhancer = ImageEnhance.Sharpness(pil_image)
    pil_image = enhancer.enhance(1.5)

    return pil_image


def _perform_ocr_on_image(pil_image):
    """Run OCR on PIL Image using EasyOCR with Tesseract fallback."""
    preprocessed = _preprocess_image(pil_image)

    # ── Primary: EasyOCR ──────────────────────────────────────────────
    if EASYOCR_AVAILABLE:
        try:
            reader = _get_easyocr_reader()
            if reader:
                import numpy as np
                img_array = np.array(preprocessed)
                results = reader.readtext(img_array, detail=1, paragraph=True)
                results.sort(key=lambda r: (min(p[1] for p in r[0]), min(p[0] for p in r[0])))
                text_lines = [result[1] for result in results]
                text = "\n".join(text_lines).strip()
                if len(text) > 5:
                    return text
        except Exception as e:
            logger.warning(f"EasyOCR failed, falling back to Tesseract: {e}")

    # ── Fallback: Tesseract ───────────────────────────────────────────
    if PYTESSERACT_AVAILABLE:
        try:
            gray_img = preprocessed.convert("L")
            custom_config = r'--oem 3 --psm 6'
            text = pytesseract.image_to_string(gray_img, config=custom_config)
            if len(text.strip()) < 10:
                text = pytesseract.image_to_string(gray_img)
            return text.strip()
        except Exception:
            try:
                return pytesseract.image_to_string(pil_image).strip()
            except Exception:
                pass

    return ""


def clean_val(val):
    """Clean extracted field value from noise, symbols, and leading/trailing colons."""
    if not val:
        return ""
    val = re.sub(r'^[^\w\s\(\)]+', '', val)
    val = re.sub(r'\s+', ' ', val)
    val = val.strip(' :-_\t\r\n"')
    val = re.sub(r'^(From|To|Attn|Attention|Subject|Sub|Re|Date|Ref|Dear|FAO|Matter|Topic)\s*[:\-]\s*', '', val, flags=re.IGNORECASE)
    return val.strip()


def parse_date(text_snippet):
    """Robust date parser supporting diverse international & regional date formats into YYYY-MM-DD."""
    if not text_snippet:
        return ""

    text_snippet = text_snippet.strip()

    # Pattern 1: YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD
    match = re.search(r'\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b', text_snippet)
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            return datetime(year, month, day).strftime('%Y-%m-%d')
        except ValueError:
            pass

    # Pattern 2: DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
    match = re.search(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b', text_snippet)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if month > 12 >= day:
            day, month = month, day
        try:
            return datetime(year, month, day).strftime('%Y-%m-%d')
        except ValueError:
            pass

    # Pattern 3: 05-AUG-2026, 5th of August 2026, 5 August 2026
    months_pattern = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'

    match = re.search(r'\b(\d{1,2})[-/\s]+(?:of\s+)?(' + months_pattern + r')[-/\s,]+(\d{4})\b', text_snippet, re.IGNORECASE)
    if match:
        day_str, month_str, year_str = match.group(1), match.group(2), match.group(3)
        for fmt in ('%d %B %Y', '%d %b %Y'):
            try:
                dt = datetime.strptime(f"{day_str} {month_str} {year_str}", fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                pass

    # Pattern 4: August 05, 2026
    match = re.search(r'\b(' + months_pattern + r')\s+(\d{1,2})(?:st|nd|rd|th)?[\s,]+(\d{4})\b', text_snippet, re.IGNORECASE)
    if match:
        month_str, day_str, year_str = match.group(1), match.group(2), match.group(3)
        for fmt in ('%B %d %Y', '%b %d %Y'):
            try:
                dt = datetime.strptime(f"{month_str} {day_str} {year_str}", fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                pass

    return ""


def parse_letter_fields(raw_text, direction="INCOMING"):
    """
    Smart Positional Layout & Structural Zone Parser.
    Divides document into structural zones to extract fields with high accuracy:
    - sender (Zone 1: Top Letterhead/Header block)
    - date & reference_no (Zone 2: Top Metadata block)
    - recipient & attention_to (Zone 3: Addressee block)
    - subject (Zone 4: Subject line / Topic block)
    """
    fields = {
        "sender": "",
        "recipient": "",
        "attention_to": "",
        "subject": "",
        "date": "",
        "reference_no": "",
    }

    if not raw_text:
        return fields

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    full_text = "\n".join(lines)
    total_lines = len(lines)

    # ------------------------------------------------------------------
    # 1. Parse Date (Zone 2 - Metadata Block & Full Text fallback)
    # ------------------------------------------------------------------
    date_match = re.search(r'\b(?:Date|Dated|Date of issue)\b\s*[:\-\s]*([^\n]+)', full_text, re.IGNORECASE)
    if date_match:
        parsed = parse_date(date_match.group(1))
        if parsed:
            fields["date"] = parsed

    if not fields["date"]:
        parsed = parse_date(full_text)
        if parsed:
            fields["date"] = parsed

    # ------------------------------------------------------------------
    # 2. Parse Sender (Zone 1 - Top Letterhead/Header Zone)
    # ------------------------------------------------------------------
    sender_match = re.search(r'\b(?:From|Sender|De|Expéditeur|Issued By|Originator|Organization|Company|Header)\b\s*[:\-\s]*([^\n]+)', full_text, re.IGNORECASE)
    if sender_match:
        fields["sender"] = clean_val(sender_match.group(1))
    else:
        # Inspect top 6 non-empty header lines (Top 25% of document)
        header_lines = lines[:min(6, total_lines)]
        noise_keywords = r'^(To|Date|Subject|Ref|Dear|Attn|Attention|Fax|Tel|Email|Phone|Page|Memorandum|Letter|Confidential|Urgent|P\.O\.Box|Addressee|Website|www\.)'
        for line in header_lines:
            if not re.search(noise_keywords, line, re.IGNORECASE) and len(line) > 3 and not line.isdigit():
                fields["sender"] = clean_val(line)
                break

    # ------------------------------------------------------------------
    # 3. Parse Recipient (Zone 3 - Addressee Block)
    # ------------------------------------------------------------------
    recipient_match = re.search(r'\b(?:To|Recipient|À|Destinataire|Deliver To|Send To|Addressee|For)\b\s*[:\-\s]*([^\n]+)', full_text, re.IGNORECASE)
    if recipient_match:
        fields["recipient"] = clean_val(recipient_match.group(1))
    else:
        # Fallback: Look in upper-middle lines for organization patterns
        org_patterns = r'^(Ministry|Department|Authority|Corporation|Commission|Agency|Bureau|Company|Enterprise|Office of|Messrs|The Manager|The Director|The Head)'
        for line in lines[1:min(12, total_lines)]:
            if re.search(org_patterns, line, re.IGNORECASE):
                fields["recipient"] = clean_val(line)
                break

    # ------------------------------------------------------------------
    # 4. Parse Attention To (Zone 3 - Addressee / Salutation)
    # ------------------------------------------------------------------
    attn_match = re.search(r'\b(?:Attn|Attention|Attention To|FAO|For the attention of|Care of|c/o|Kind Attn|To the Attention of)\b\s*[:\-\s]*([^\n]+)', full_text, re.IGNORECASE)
    if attn_match:
        fields["attention_to"] = clean_val(attn_match.group(1))
    else:
        # Salutation check (e.g. "Dear Mr. Abenezer", "Dear Dr. Sarah")
        salutation_match = re.search(r'\bDear\s+((?:Mr\.|Ms\.|Mrs\.|Dr\.|Eng\.|Prof\.)\s+[A-Za-z\s]+)', full_text, re.IGNORECASE)
        if salutation_match:
            fields["attention_to"] = clean_val(salutation_match.group(1))

    # ------------------------------------------------------------------
    # 5. Parse Subject (Zone 4 - Topic Block)
    # ------------------------------------------------------------------
    subject_match = re.search(r'\b(?:Subject|Sub|Re|Ref Subject|Objet|Title|Regarding|Concern|Topic|Matter|SUBJ)\b\s*[:\-\s]*([^\n]+(?:\n[^\n]+){0,2})', full_text, re.IGNORECASE)
    if subject_match:
        raw_subj = subject_match.group(1).strip()
        raw_subj = re.split(r'\n(?=Dear|Attn|Date|Ref|To:|From:|Sincerely|Regards|Thank you)', raw_subj, flags=re.IGNORECASE)[0]
        fields["subject"] = clean_val(raw_subj)[:280]
    else:
        # Fallback: scan lines for standalone "RE:" or bold topic header
        for line in lines:
            if re.match(r'^\b(?:RE|RE:)\b\s+', line, re.IGNORECASE):
                fields["subject"] = clean_val(re.sub(r'^\b(?:RE|RE:)\b\s+', '', line, flags=re.IGNORECASE))[:280]
                break

    # ------------------------------------------------------------------
    # 6. Parse Reference No (Zone 2 - Metadata Block, ONLY for incoming letters)
    # ------------------------------------------------------------------
    if direction != "OUTGOING":
        ref_match = re.search(r'\b(?:Ref No|Reference No|Ref Number|Our Ref|Your Ref|Ref|Reference|Ref\s*#|N/Ref|V/Ref|File Ref)\b\s*[:\-\s]*([A-Za-z0-9/\-_.]+)', full_text, re.IGNORECASE)
        if ref_match:
            ref_val = clean_val(ref_match.group(1))
            if not re.match(r'^(Date|Subject|Dear|To|From|Attn|Page|Tel|Fax)$', ref_val, re.IGNORECASE) and len(ref_val) > 1:
                fields["reference_no"] = ref_val

    return fields
