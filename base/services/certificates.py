from io import BytesIO
import os
import qrcode
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.utils import timezone
from reportlab.lib.pagesizes import A4, A5, landscape
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from base.models import BabyDedication, Baptism, Certificate, Officiant, Wedding


def _register_poppins():
    font_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "fonts", "Poppins")
    weights = [
        ("Poppins", "Poppins-Regular.ttf"),
        ("Poppins-Medium", "Poppins-Medium.ttf"),
        ("Poppins-SemiBold", "Poppins-SemiBold.ttf"),
        ("Poppins-Bold", "Poppins-Bold.ttf"),
        ("Poppins-Italic", "Poppins-Italic.ttf"),
        ("Poppins-BoldItalic", "Poppins-BoldItalic.ttf"),
    ]
    registered = pdfmetrics.getRegisteredFontNames()
    for name, filename in weights:
        path = os.path.join(font_dir, filename)
        if os.path.exists(path) and name not in registered:
            pdfmetrics.registerFont(TTFont(name, path))
    try:
        pdfmetrics.registerFontFamily(
            "Poppins",
            normal="Poppins",
            bold="Poppins-Bold",
            italic="Poppins-Italic",
            boldItalic="Poppins-BoldItalic",
        )
    except Exception:
        pass


_register_poppins()


CERTIFICATE_DESIGN_OPTIONS = {
    Certificate.BAPTISM: [
        ("baptism_og", "New Life OG Classic"),
        ("baptism_blue_cross", "Blue Cross Classic"),
        ("baptism_white_gold", "White & Gold Formal"),
    ],
    Certificate.DEDICATION: [
        ("dedication_new_life", "New Life Classic (Custom)"),
        ("dedication_cream_gold", "Cream Gold Elegant"),
        ("dedication_green_leaf", "Green Leaf Blessing"),
    ],
    Certificate.WEDDING: [
        ("wedding_og", "Wedding OG Classic"),
        ("wedding_ivory_gold", "Ivory Gold Formal"),
        ("wedding_royal_navy", "Royal Navy Signature"),
    ],
}


def get_design_options(service_type: str):
    return CERTIFICATE_DESIGN_OPTIONS.get(service_type, [])


def _is_valid_design(service_type: str, design_template: str) -> bool:
    valid_codes = {code for code, _ in get_design_options(service_type)}
    return design_template in valid_codes


def _verify_url(certificate_number: str) -> str:
    base = getattr(settings, "SITE_BASE_URL", "http://127.0.0.1:8000")
    return f"{base}/verify/{certificate_number}/"


def _qr_content(certificate_number: str):
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(_verify_url(certificate_number))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    stream = BytesIO()
    img.save(stream, format="PNG")
    return stream.getvalue()


def _save_certificate_pdf(certificate: Certificate, draw_fn):
    pdf_bytes = _render_pdf_bytes(certificate, draw_fn)

    file_name = f"{certificate.certificate_number}-{timezone.now().strftime('%Y%m%d%H%M%S')}.pdf"
    certificate.certificate_file.save(file_name, ContentFile(pdf_bytes), save=False)

    qr_data = _qr_content(certificate.certificate_number)
    certificate.qr_code_image.save(f"{certificate.certificate_number}.png", ContentFile(qr_data), save=False)
    certificate.save(update_fields=["certificate_file", "qr_code_image", "updated_at"])


def _render_pdf_bytes(certificate: Certificate, draw_fn) -> bytes:
    page_size = _certificate_page_size(certificate)
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=page_size)
    draw_fn(c, certificate)
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


def _certificate_page_size(certificate: Certificate):
    if certificate.service_type == Certificate.DEDICATION and certificate.design_template == "dedication_new_life":
        return landscape(A5)
    if certificate.service_type == Certificate.WEDDING and certificate.design_template == "wedding_og":
        return landscape(A5)
    if certificate.service_type == Certificate.BAPTISM and certificate.design_template == "baptism_og":
        return A5
    return landscape(A4)


def _draw_common(c, title: str, subtitle: str, names: str, service_date: str, officiant: str, cert_number: str, palette):
    width, height = landscape(A4)
    bg, accent, text = palette

    c.setFillColor(bg)
    c.rect(0, 0, width, height, fill=1, stroke=0)

    c.setStrokeColor(accent)
    c.setLineWidth(4)
    c.rect(1 * cm, 1 * cm, width - 2 * cm, height - 2 * cm, fill=0, stroke=1)

    c.setFillColor(text)
    c.setFont("Times-Bold", 34)
    c.drawCentredString(width / 2, height - 4 * cm, title)

    c.setFont("Times-Italic", 18)
    c.drawCentredString(width / 2, height - 5.2 * cm, subtitle)

    c.setFont("Times-Bold", 28)
    c.drawCentredString(width / 2, height - 8 * cm, names)

    c.setFont("Helvetica", 14)
    c.drawCentredString(width / 2, height - 10 * cm, f"Service Date: {service_date}")
    c.drawCentredString(width / 2, height - 11 * cm, f"Officiant: {officiant or 'N/A'}")
    c.drawCentredString(width / 2, height - 12 * cm, f"Certificate No: {cert_number}")

    _draw_officiant_signature(c, officiant, accent)


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _resolve_officiant_signature(officiant_label: str):
    normalized_label = _normalize_text(officiant_label)
    if not normalized_label:
        return None, None

    for officiant in Officiant.objects.all():
        if not officiant.signature_image:
            continue
        display_text = _normalize_text(str(officiant))
        name_text = _normalize_text(officiant.name)
        if normalized_label == display_text or normalized_label == name_text:
            return officiant.signature_image.path, str(officiant)

    return None, None


def _draw_officiant_signature(c, officiant_label: str, accent_color):
    width, _ = landscape(A4)
    signature_path, signature_name = _resolve_officiant_signature(officiant_label)

    line_left = width - 9.3 * cm
    line_right = width - 3.0 * cm
    line_y = 2.0 * cm

    if signature_path:
        try:
            c.drawImage(
                ImageReader(signature_path),
                line_left,
                line_y + 0.2 * cm,
                width=(line_right - line_left),
                height=1.7 * cm,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pass

    c.setStrokeColor(accent_color)
    c.setLineWidth(1)
    c.line(line_left, line_y, line_right, line_y)
    c.setFillColor(accent_color)
    c.setFont("Helvetica", 10)
    c.drawCentredString((line_left + line_right) / 2, line_y - 0.45 * cm, signature_name or officiant_label or "Officiant")


def _draw_center_wrapped(c, text: str, center_x: float, start_y: float, max_width: float, line_height: float = 16):
    if not text:
        return start_y

    words = str(text).split()
    if not words:
        return start_y

    lines = []
    current_line = []
    for word in words:
        tentative = " ".join(current_line + [word])
        if c.stringWidth(tentative, c._fontname, c._fontsize) <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))

    y = start_y
    for line in lines[:4]:
        c.drawCentredString(center_x, y, line)
        y -= line_height
    return y


def _draw_left_wrapped(c, text: str, x: float, start_y: float, max_width: float, line_height: float = 14, max_lines: int = 5):
    if not text:
        return start_y

    words = str(text).split()
    if not words:
        return start_y

    lines = []
    current_line = []
    for word in words:
        tentative = " ".join(current_line + [word])
        if c.stringWidth(tentative, c._fontname, c._fontsize) <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))

    y = start_y
    for line in lines[:max_lines]:
        c.drawString(x, y, line)
        y -= line_height
    return y


def _design_asset_path(filename: str) -> str:
    return os.path.join(settings.BASE_DIR, "static", "images", "certificate_designs", filename)


def _draw_new_life_dedication(c, dedication: BabyDedication, certificate: Certificate):
    # ===== EDIT ZONE 1: PAGE SIZE =====
    # Change A5 -> A4 (or other) if you want a different certificate canvas.
    width, height = c._pagesize

    # ===== EDIT ZONE 2: DESIGN ASSETS (BACKGROUND/LOGO FILENAMES) =====
    background_path = _design_asset_path("dedication.png")
    logo_path = _design_asset_path("NL Logo.png")

    # ===== EDIT ZONE 3: BACKGROUND RENDERING =====
    if os.path.exists(background_path):
        c.drawImage(background_path, 0, 0, width=width, height=height, preserveAspectRatio=False, mask="auto")
    else:
        c.setFillColor("#f4efd0")
        c.rect(0, 0, width, height, fill=1, stroke=0)

    # ===== EDIT ZONE 4: TOP LOGO POSITION + SIZE =====
    if os.path.exists(logo_path):
        c.drawImage(
            logo_path,
            width / 2 - 2.20 * cm,
            height - 4.75 * cm,
            width=3.9 * cm,
            height=3.9 * cm,
            preserveAspectRatio=True,
            mask="auto",
        )

    # ===== EDIT ZONE 5: TITLE LINES + TITLE STYLE =====
    # NOTE: dedication.png already has printed title text. We mask this area first,
    # then draw dynamic title so your edits are visible.
    title_y = height - 4.7 * cm


    c.setStrokeColor("#111111")
    c.setLineWidth(1.5)
    c.line(width * 0.16, title_y + 0.03 * cm, width * 0.32, title_y + 0.03 * cm)
    c.line(width * 0.70, title_y + 0.03 * cm, width * 0.84, title_y + 0.03 * cm)

    c.setFillColor("#111111")
    c.setFont("Times-Italic", 32)
    dedication_title = "Baby Dedication"
    c.drawCentredString(width / 2 + 0.15 * cm, title_y - 0.32 * cm, dedication_title)

    # ===== EDIT ZONE 6: DYNAMIC DATES =====
    born_date = dedication.child.date_of_birth.strftime("%d/%m/%Y") if dedication.child.date_of_birth else "N/A"
    dedication_date = dedication.dedication_date.strftime("%d/%m/%Y") if dedication.dedication_date else "N/A"
    dedication_year = dedication.dedication_date.year if dedication.dedication_date else timezone.localdate().year

    # ===== EDIT ZONE 7: MAIN CENTER TEXT BLOCK =====
    c.setFont("Helvetica", 14)
    c.drawCentredString(width / 2, height - 5.9 * cm, "This is to certify that")

    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(width / 2, height - 6.95 * cm, str(dedication.child).upper())

    c.setFont("Helvetica", 12)
    c.drawCentredString(width / 2, height - 7.95 * cm, f"Born on {born_date} was dedicated to God")
    c.drawCentredString(width / 2, height - 8.75 * cm, f"on {dedication_date} in the year {dedication_year}")
    c.drawCentredString(width / 2, height - 9.45 * cm, "at New Life  - Kigali")

    # ===== EDIT ZONE 8: VERSE BLOCK (BOTTOM-LEFT) =====
    c.setFont("Helvetica-Bold", 9)
    c.drawString(1.15 * cm, 3.55 * cm, f"Verse: {dedication.scripture_reference or 'N/A'}")
    c.setFont("Times-Italic", 9)
    _draw_left_wrapped(
        c,
        f'“ {dedication.scripture_text or ""}”',
        1.15 * cm,
        3.10 * cm,
        max_width=7.7 * cm,
        line_height=0.45 * cm,
        max_lines=4,
    )

    # ===== EDIT ZONE 9: FAMILY + OFFICIANT BLOCK (BOTTOM-RIGHT) =====
    c.setFont("Helvetica-Bold", 9)
    right_x = width * 0.70
    c.drawString(right_x, 3.55 * cm, f"Father: {dedication.father}")
    c.drawString(right_x, 3.10 * cm, f"Mother: {dedication.mother}")
    c.drawString(right_x, 2.10 * cm, f"Officiant: {dedication.officiant or 'N/A'}")

    # ===== EDIT ZONE 10: OFFICIANT SIGNATURE IMAGE =====
    signature_path, _ = _resolve_officiant_signature(dedication.officiant)
    if signature_path:
        try:
            c.drawImage(signature_path, width * 0.56, 0.40 * cm, width=3.8 * cm, height=1.5 * cm, preserveAspectRatio=True, mask="auto")
        except Exception:
            pass

    # ===== EDIT ZONE 11: CERTIFICATE NUMBER FOOTER =====
    c.setFont("Helvetica", 6.5)
    c.setFillColor("#313131")
    c.drawRightString(width - 0.7 * cm, 0.35 * cm, f"No: {certificate.certificate_number}")


def _draw_baptism_og(c, certificate: Certificate):
    """New Life OG Classic — A5 portrait with pre-designed background."""
    baptism = certificate.linked_object
    width, height = c._pagesize  # A5 portrait: ~419 × 595 pts

    bg_path = _design_asset_path("Baptism OG.png")
    if os.path.exists(bg_path):
        c.drawImage(bg_path, 0, 0, width=width, height=height,
                    preserveAspectRatio=False, mask="auto")
    else:
        c.setFillColor("#FFFDF5")
        c.rect(0, 0, width, height, fill=1, stroke=0)

    text_color = "#2C3530"
    cx = width / 2

    c.setFillColor(text_color)
    c.setFont("Poppins", 11)
    c.drawCentredString(cx, 422, "This is to certify that")
    c.drawCentredString(cx, 410, "Turemeza ko")

    c.setFont("Poppins-SemiBold", 13)
    c.drawCentredString(cx, 387, str(baptism.person))

    c.setFont("Poppins", 11)
    c.drawCentredString(cx, 363, "Was baptized by immersion on")
    c.drawCentredString(cx, 351, "Yabatijwe mu mazi magari kuwa")

    c.setFont("Poppins-SemiBold", 13)
    if baptism.baptism_date:
        date_str = f"{baptism.baptism_date.day} {baptism.baptism_date.strftime('%B %Y')}"
    else:
        date_str = "—"
    c.drawCentredString(cx, 320, date_str)

    c.setFont("Poppins", 11)
    c.drawCentredString(cx, 295, "At")
    c.drawCentredString(cx, 283, "Yabatirijwe")

    c.setFont("Poppins-Bold", 12)
    c.drawCentredString(cx, 258, "NEW LIFE BIBLE CHURCH-KIGALI")


def _draw_baptism(c, certificate: Certificate):
    baptism = certificate.linked_object
    if certificate.design_template == "baptism_og":
        _draw_baptism_og(c, certificate)
        return
    if certificate.design_template == "baptism_white_gold":
        _draw_common(
            c,
            title="Holy Baptism Certificate",
            subtitle="This is to certify with joy that",
            names=str(baptism.person),
            service_date=baptism.baptism_date.strftime("%d %b %Y") if baptism.baptism_date else "N/A",
            officiant=baptism.officiant,
            cert_number=certificate.certificate_number,
            palette=("#FFFDF8", "#B58A3A", "#5B4521"),
        )
        width, height = landscape(A4)
        c.setFont("Times-Bold", 36)
        c.setFillColor("#D7BE87")
        c.drawCentredString(width / 2, height / 2 + 1 * cm, "✝")
        return

    _draw_common(
        c,
        title="Baptism Certificate",
        subtitle="This certifies that",
        names=str(baptism.person),
        service_date=baptism.baptism_date.strftime("%d %b %Y") if baptism.baptism_date else "N/A",
        officiant=baptism.officiant,
        cert_number=certificate.certificate_number,
        palette=("#EAF4FF", "#2F6FAB", "#123D6B"),
    )
    width, height = landscape(A4)
    c.setFont("Helvetica-Bold", 90)
    c.setFillColor("#BFD9F5")
    c.drawCentredString(width / 2, height / 2, "✝")


def _draw_dedication(c, certificate: Certificate):
    dedication = certificate.linked_object
    scripture_reference = dedication.scripture_reference or "Scripture"
    scripture_text = dedication.scripture_text or ""
    if certificate.design_template == "dedication_new_life":
        _draw_new_life_dedication(c, dedication, certificate)
        return

    if certificate.design_template == "dedication_green_leaf":
        _draw_common(
            c,
            title="Child Dedication Certificate",
            subtitle="In gratitude to God, we dedicate",
            names=str(dedication.child),
            service_date=dedication.dedication_date.strftime("%d %b %Y") if dedication.dedication_date else "N/A",
            officiant=dedication.officiant,
            cert_number=certificate.certificate_number,
            palette=("#F4FFF4", "#2E7D32", "#1E4620"),
        )
        width, height = landscape(A4)
        c.setFont("Times-Italic", 18)
        c.setFillColor("#2E7D32")
        c.drawCentredString(width / 2, height / 2 - 2 * cm, "Blessed in faith, hope, and love")
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(width / 2, height / 2 - 3.1 * cm, scripture_reference)
        c.setFont("Times-Italic", 12)
        _draw_center_wrapped(c, f'"{scripture_text}"', width / 2, height / 2 - 3.8 * cm, max_width=20 * cm, line_height=14)
        return

    _draw_common(
        c,
        title="Baby Dedication Certificate",
        subtitle="Presented with grace and thanksgiving for",
        names=str(dedication.child),
        service_date=dedication.dedication_date.strftime("%d %b %Y") if dedication.dedication_date else "N/A",
        officiant=dedication.officiant,
        cert_number=certificate.certificate_number,
        palette=("#FFF9EE", "#B28A3E", "#6F4E1E"),
    )
    width, height = landscape(A4)
    c.setFont("Times-Italic", 22)
    c.setFillColor("#B28A3E")
    c.drawCentredString(width / 2, height / 2 - 2 * cm, "Dedicated before God in love and faith")
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, height / 2 - 3.1 * cm, scripture_reference)
    c.setFont("Times-Italic", 12)
    _draw_center_wrapped(c, f'"{scripture_text}"', width / 2, height / 2 - 3.8 * cm, max_width=20 * cm, line_height=14)


def _draw_wedding_og(c, certificate: Certificate):
    """Wedding OG Classic design — A5 landscape with pre-designed background and overlay text."""
    wedding = certificate.linked_object
    width, height = c._pagesize  # A5 landscape: 595 x 419 pts

    # === BACKGROUND ===
    bg_path = _design_asset_path("Wedding OG.png")
    if os.path.exists(bg_path):
        c.drawImage(bg_path, 0, 0, width=width, height=height, preserveAspectRatio=False, mask="auto")
    else:
        c.setFillColor("#FFFDF5")
        c.rect(0, 0, width, height, fill=1, stroke=0)

    # === COUPLE PHOTO (circular crop) ===
    if wedding.couple_photo and os.path.exists(wedding.couple_photo.path):
        try:
            photo_reader = ImageReader(wedding.couple_photo.path)
            # Circle center and radius — measured from Wedding OG.png gold ring position
            cx, cy, r = 107, 150, 100
            # Save state, clip to circle, draw image, restore
            c.saveState()
            p = c.beginPath()
            p.circle(cx, cy, r)
            c.clipPath(p, stroke=0)
            # Draw the photo filling the circle bounding box
            c.drawImage(photo_reader, cx - r, cy - r, width=r * 2, height=r * 2, preserveAspectRatio=True, mask="auto")
            c.restoreState()
        except Exception:
            pass

    # === RIGHT PANEL TEXT OVERLAY ===
    # Colors
    dark_color = "#2C2C2C"
    gold_color = "#C9A84C"
    gray_color = "#888888"

    # "CERTIFICATE" — large bold serif
    c.setFillColor(dark_color)
    c.setFont("Times-Bold", 32)
    c.drawCentredString(330, 310, "CERTIFICATE")

    # "OF MARRIAGE" — gold spaced uppercase
    c.setFillColor(gold_color)
    c.setFont("Times-Bold", 14)
    c.drawCentredString(330, 290, "O F   M A R R I A G E")

    # Legal text — small gray
    c.setFillColor(gray_color)
    c.setFont("Times-Roman", 12)
    c.drawCentredString(330, 274, "ACCORDING TO THE ORDINANCES OF GOD AND THE")
    c.drawCentredString(330, 264, "LAWS OF THE REPUBLIC OF RWANDA")

    # Couple names — gold bold italic
    c.setFillColor(gold_color)
    c.setFont("Times-BoldItalic", 15)
    couple_names = f"{wedding.groom} & {wedding.bride}"
    c.drawCentredString(370, 220, couple_names)

    # Wedding details — dark spaced uppercase
    c.setFillColor(dark_color)
    c.setFont("Times-Roman", 9)

    # Format date nicely
    if wedding.wedding_date:
        day = wedding.wedding_date.strftime("%d").lstrip("0")
        month = wedding.wedding_date.strftime("%B").upper()
        year = wedding.wedding_date.year
        date_str = f"{day}TH DAY OF {month} THE YEAR OF OUR LORD {year}"
    else:
        date_str = "N/A"

    c.drawCentredString(370, 190, f"WERE UNITED IN THE HOLY MATRIMONY,")
    c.drawCentredString(370, 180, f" ON {date_str} AT NEW LIFE")


    # === SIGNATURE SECTION ===
    sig_y = 105
    line_width = 65

    # Left column: GROOM + MINISTER
    # GROOM line
    c.setStrokeColor(dark_color)
    c.setLineWidth(1)
    c.line(220, sig_y + 15, 250 + line_width, sig_y + 15)
    c.setFillColor(gray_color)
    c.setFont("Times-Roman", 8)
    c.drawCentredString(250 + line_width / 2, sig_y + 6, "GROOM")

    # MINISTER line
    c.setStrokeColor(dark_color)
    c.line(220, sig_y - 10, 250 + line_width, sig_y - 10)
    c.setFillColor(gray_color)
    c.setFont("Times-Roman", 8)
    c.drawCentredString(250 + line_width / 2, sig_y - 19, "MINISTER")


    # Right column: BRIDE + WITNESSES
    # BRIDE line
    c.setStrokeColor(dark_color)
    c.setLineWidth(0.5)
    c.line(375, sig_y + 15, 400 + line_width, sig_y + 15)
    c.setFillColor(gray_color)
    c.setFont("Times-Roman", 8)
    c.drawCentredString(375 + line_width / 2, sig_y + 6, "BRIDE")

    # WITNESSES line
    c.setStrokeColor(dark_color)
    c.line(375, sig_y - 10, 400 + line_width, sig_y - 10)
    c.line(375, sig_y - 25, 400 + line_width, sig_y - 25)
    c.line(375, sig_y - 40, 400 + line_width, sig_y - 40)
    c.setFillColor(gray_color)
    c.setFont("Times-Roman", 8)
    c.drawCentredString(375 + line_width / 2, sig_y - 50, "WITNESSES")
    c.setFont("Times-Italic", 8)

    # === FOOTER BIBLE VERSE ===
    c.setFillColor(gray_color)
    c.setFont("Times-Italic", 8)
    c.drawCentredString(365, 13, '"What therefore God hath joined together, let no man put asunder. — Matthew 19:6"')

    # === CERTIFICATE NUMBER (bottom right) ===
    c.setFont("Times-Roman", 5.5)
    c.setFillColor(gray_color)
    c.drawRightString(width - 20, 12, f"No: {certificate.certificate_number}")


def _draw_wedding(c, certificate: Certificate):
    wedding = certificate.linked_object

    if certificate.design_template == "wedding_og":
        _draw_wedding_og(c, certificate)
        return

    if certificate.design_template == "wedding_royal_navy":
        _draw_common(
            c,
            title="Marriage Covenant Certificate",
            subtitle="This certifies the covenant union of",
            names=f"{wedding.groom} & {wedding.bride}",
            service_date=wedding.wedding_date.strftime("%d %b %Y"),
            officiant=wedding.officiant,
            cert_number=certificate.certificate_number,
            palette=("#F5F8FF", "#1B3A6F", "#14233F"),
        )
        width, height = landscape(A4)
        c.setFont("Times-Italic", 16)
        c.setFillColor("#1B3A6F")
        c.drawCentredString(width / 2, height / 2 - 2 * cm, "United in holy matrimony")
        return

    _draw_common(
        c,
        title="Marriage Certificate",
        subtitle="This certifies the holy union of",
        names=f"{wedding.groom} & {wedding.bride}",
        service_date=wedding.wedding_date.strftime("%d %b %Y"),
        officiant=wedding.officiant,
        cert_number=certificate.certificate_number,
        palette=("#FFFDF5", "#9D7A3A", "#4D3B1F"),
    )


def _create_or_get_certificate(service_type: str, linked_object, design_template: str) -> Certificate:
    if not _is_valid_design(service_type, design_template):
        raise ValueError("Invalid design template for selected service type.")

    content_type = ContentType.objects.get_for_model(linked_object.__class__)
    certificate, _ = Certificate.objects.get_or_create(
        service_type=service_type,
        content_type=content_type,
        object_id=linked_object.id,
        defaults={"design_template": design_template},
    )
    if certificate.design_template != design_template:
        certificate.design_template = design_template
        certificate.save(update_fields=["design_template", "updated_at"])
    return certificate


def render_baptism_preview_pdf(baptism: Baptism, design_template: str) -> bytes:
    if not _is_valid_design(Certificate.BAPTISM, design_template):
        raise ValueError("Invalid design template for selected service type.")

    preview_certificate = Certificate(
        service_type=Certificate.BAPTISM,
        design_template=design_template,
        issued_date=timezone.localdate(),
    )
    preview_certificate.certificate_number = f"PREVIEW-{timezone.now().strftime('%H%M%S')}"
    preview_certificate.linked_object = baptism

    return _render_pdf_bytes(preview_certificate, _draw_baptism)


def generate_baptism_certificate(baptism: Baptism, design_template: str = "baptism_og") -> Certificate:
    certificate = _create_or_get_certificate(Certificate.BAPTISM, baptism, design_template)
    _save_certificate_pdf(certificate, _draw_baptism)
    baptism.certificate_generated = True
    baptism.status = "Completed" if baptism.status != "Completed" else baptism.status
    baptism.save(update_fields=["certificate_generated", "status", "updated_at"])
    return certificate


def generate_dedication_certificate(dedication: BabyDedication, design_template: str = "dedication_cream_gold") -> Certificate:
    certificate = _create_or_get_certificate(Certificate.DEDICATION, dedication, design_template)
    _save_certificate_pdf(certificate, _draw_dedication)
    dedication.certificate_generated = True
    dedication.status = "Completed" if dedication.status != "Completed" else dedication.status
    dedication.save(update_fields=["certificate_generated", "status", "updated_at"])
    return certificate


def generate_wedding_certificate(wedding: Wedding, design_template: str = "wedding_ivory_gold") -> Certificate:
    certificate = _create_or_get_certificate(Certificate.WEDDING, wedding, design_template)
    _save_certificate_pdf(certificate, _draw_wedding)
    wedding.certificate_generated = True
    wedding.status = "Completed" if wedding.status != "Completed" else wedding.status
    wedding.save(update_fields=["certificate_generated", "status", "updated_at"])
    return certificate


def render_wedding_preview_pdf(wedding: Wedding, design_template: str) -> bytes:
    if not _is_valid_design(Certificate.WEDDING, design_template):
        raise ValueError("Invalid design template for selected service type.")

    preview_certificate = Certificate(
        service_type=Certificate.WEDDING,
        design_template=design_template,
        issued_date=timezone.localdate(),
    )
    preview_certificate.certificate_number = f"PREVIEW-{timezone.now().strftime('%H%M%S')}"
    preview_certificate.linked_object = wedding

    return _render_pdf_bytes(preview_certificate, _draw_wedding)


def render_dedication_preview_pdf(dedication: BabyDedication, design_template: str) -> bytes:
    if not _is_valid_design(Certificate.DEDICATION, design_template):
        raise ValueError("Invalid design template for selected service type.")

    preview_certificate = Certificate(
        service_type=Certificate.DEDICATION,
        design_template=design_template,
        issued_date=timezone.localdate(),
    )
    preview_certificate.certificate_number = f"PREVIEW-{timezone.now().strftime('%H%M%S')}"
    preview_certificate.linked_object = dedication

    return _render_pdf_bytes(preview_certificate, _draw_dedication)
