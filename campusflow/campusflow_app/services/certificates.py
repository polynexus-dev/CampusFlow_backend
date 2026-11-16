"""
Certificate rendering, issuing and PDFs; student ID cards.
Docs/college_gap_closure_plan.md §1.1.

Placeholders are substituted with a regex over {word} tokens only. This is
deliberately not str.format / Django templates: an admin-edited template
must not be able to reach attributes ("{x.__class__}") or template tags.
Unknown placeholders are left in place so a typo is visible on the preview
instead of silently printing nothing.
"""
import io
import re

from django.db import connection, transaction
from django.utils import timezone

from ..models.certificates import CertificateRequest, CertificateTemplate, IssuedCertificate
from ..models.clearance import ClearanceRequest
from .academics import get_current_term
from .clearance import is_student_cleared

PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

DEFAULT_TEMPLATES = [
    {
        "name": "Bonafide Certificate",
        "cert_type": CertificateTemplate.TYPE_BONAFIDE,
        "title": "BONAFIDE CERTIFICATE",
        "body_text": (
            "This is to certify that {student_name} (Roll / ID No. {student_id}), son/daughter of "
            "{guardian_name}, is a bonafide student of this institution, studying in {program}, "
            "{semester}, Department of {department}, for the academic year {academic_year}.\n\n"
            "This certificate is issued on the request of the student for the purpose of {purpose}."
        ),
        "requires_approval": True,
        "requires_final_clearance": False,
    },
    {
        "name": "Character Certificate",
        "cert_type": CertificateTemplate.TYPE_CHARACTER,
        "title": "CHARACTER CERTIFICATE",
        "body_text": (
            "This is to certify that {student_name} (Roll / ID No. {student_id}) has been a student "
            "of this institution in the Department of {department}. To the best of my knowledge, "
            "the student bears a good moral character and conduct."
        ),
        "requires_approval": True,
        "requires_final_clearance": False,
    },
    {
        "name": "Leaving Certificate",
        "cert_type": CertificateTemplate.TYPE_LEAVING,
        "title": "LEAVING / TRANSFER CERTIFICATE",
        "body_text": (
            "This is to certify that {student_name} (Roll / ID No. {student_id}), date of birth "
            "{date_of_birth}, was admitted to this institution on {admission_date} and was studying "
            "in {program}, Department of {department}.\n\n"
            "Reason for leaving: {reason_for_leaving}\n"
            "Conduct: {conduct}\n\n"
            "All dues to the institution have been cleared."
        ),
        "requires_approval": True,
        "requires_final_clearance": True,
    },
    {
        "name": "Course Completion Certificate",
        "cert_type": CertificateTemplate.TYPE_COURSE_COMPLETION,
        "title": "COURSE COMPLETION CERTIFICATE",
        "body_text": (
            "This is to certify that {student_name} (Roll / ID No. {student_id}) has completed the "
            "{program} programme in the Department of {department} (batch {batch})."
        ),
        "requires_approval": True,
        "requires_final_clearance": False,
    },
]


class CertificateError(Exception):
    """A business-rule refusal (e.g. clearance pending). Message is user-facing."""


def ensure_default_templates():
    """Seed the standard templates the first time a college opens the module."""
    if CertificateTemplate.objects.exists():
        return
    for spec in DEFAULT_TEMPLATES:
        CertificateTemplate.objects.create(**spec)


def college_name():
    return getattr(connection.tenant, "name", "") or connection.schema_name


def _fmt_date(value):
    return value.strftime("%d %b %Y") if value else ""


def build_context(student, purpose="", extra_context=None, certificate_number=""):
    user = student.user
    term = get_current_term()
    context = {
        "student_name": user.get_full_name() or user.username,
        "student_id": student.student_id,
        "guardian_name": student.parent_guardian_name or "",
        "department": student.department.name if student.department else "",
        "program": student.program_enrolled_in or "",
        "semester": student.current_semester_year or "",
        "batch": student.batch_academic_year or "",
        "date_of_birth": _fmt_date(student.date_of_birth),
        "admission_date": _fmt_date(student.admission_date),
        "academic_year": term.academic_year.name if term else "",
        "college_name": college_name(),
        "today": _fmt_date(timezone.localdate()),
        "purpose": purpose or "",
        "certificate_number": certificate_number,
    }
    for key, value in (extra_context or {}).items():
        if PLACEHOLDER_RE.fullmatch("{" + str(key) + "}"):
            context[str(key)] = "" if value is None else str(value)
    return context


def render_text(text, context):
    return PLACEHOLDER_RE.sub(lambda m: context.get(m.group(1), m.group(0)), text)


def check_can_issue(template, student):
    if not template.is_active:
        raise CertificateError("This certificate template is inactive.")
    if template.requires_final_clearance:
        cleared, _ = is_student_cleared(student, cycle_type=ClearanceRequest.CYCLE_FINAL_EXIT)
        if not cleared:
            raise CertificateError(
                "This certificate needs the student's final-exit (No-Dues) clearance to be complete first."
            )


@transaction.atomic
def issue_certificate(template, student, issued_by, purpose="", extra_context=None):
    check_can_issue(template, student)
    certificate = IssuedCertificate(
        template=template, student=student, purpose=purpose or "",
        extra_context=extra_context or {}, issued_by=issued_by,
    )
    context = build_context(
        student, purpose=purpose, extra_context=extra_context,
        certificate_number=certificate.certificate_number,
    )
    certificate.rendered_title = render_text(template.title, context)
    certificate.rendered_body = render_text(template.body_text, context)
    certificate.save()
    return certificate


@transaction.atomic
def approve_request(cert_request, reviewer, extra_context=None, remarks=""):
    if cert_request.status != CertificateRequest.STATUS_PENDING:
        raise CertificateError(f"This request is already {cert_request.status}.")
    certificate = issue_certificate(
        cert_request.template, cert_request.student, issued_by=reviewer,
        purpose=cert_request.purpose, extra_context=extra_context,
    )
    cert_request.status = CertificateRequest.STATUS_ISSUED
    cert_request.issued_certificate = certificate
    cert_request.reviewed_by = reviewer
    cert_request.reviewed_at = timezone.now()
    cert_request.remarks = remarks or ""
    cert_request.save(update_fields=["status", "issued_certificate", "reviewed_by", "reviewed_at", "remarks"])
    return certificate


def verification_path(certificate):
    """Public, unauthenticated verify endpoint. Carries the schema so it
    resolves without an X-Tenant header or login (e.g. scanned by a bank)."""
    return f"/api/certificates/verify/{connection.schema_name}/{certificate.verification_token}/"


# ── PDFs ────────────────────────────────────────────────────────────────────

def _qr_image(payload, size_cm):
    import qrcode
    from reportlab.lib.units import cm
    from reportlab.platypus import Image

    buffer = io.BytesIO()
    qrcode.make(payload, box_size=6, border=1).save(buffer, format="PNG")
    buffer.seek(0)
    return Image(buffer, width=size_cm * cm, height=size_cm * cm)


def _logo_image(width_cm, height_cm):
    from reportlab.lib.units import cm
    from reportlab.platypus import Image

    logo = getattr(connection.tenant, "logo", None)
    if not logo:
        return None
    try:
        with logo.open("rb") as handle:
            buffer = io.BytesIO(handle.read())
        return Image(buffer, width=width_cm * cm, height=height_cm * cm, kind="proportional")
    except Exception:
        return None


def certificate_pdf(certificate, verify_url):
    """A4 certificate: letterhead, title, body, number/date, QR, signature line."""
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    college = ParagraphStyle("college", parent=styles["Title"], fontSize=18, leading=22)
    address = ParagraphStyle("addr", parent=styles["Normal"], alignment=TA_CENTER, fontSize=9, textColor=colors.grey)
    title = ParagraphStyle("title", parent=styles["Heading1"], alignment=TA_CENTER, fontSize=15, spaceBefore=18, spaceAfter=18)
    body = ParagraphStyle("body", parent=styles["Normal"], alignment=TA_JUSTIFY, fontSize=11.5, leading=19)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm,
                            topMargin=1.8 * cm, bottomMargin=1.8 * cm,
                            title=certificate.rendered_title)
    story = []
    logo = _logo_image(2.2, 2.2)
    if logo is not None:
        story.append(logo)
    story.append(Paragraph(escape(college_name()), college))
    tenant_address = getattr(connection.tenant, "address", "") or ""
    if tenant_address:
        story.append(Paragraph(escape(tenant_address), address))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Table([[""]], colWidths=[16.6 * cm], style=TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1.2, colors.HexColor("#1F3A5F")),
    ])))
    story.append(Table(
        [[Paragraph(f"No.: {escape(certificate.certificate_number)}", small),
          Paragraph(f"Date: {_fmt_date(timezone.localtime(certificate.issued_at).date())}", small)]],
        colWidths=[8.3 * cm, 8.3 * cm],
        style=TableStyle([("ALIGN", (1, 0), (1, 0), "RIGHT")]),
    ))
    story.append(Paragraph(escape(certificate.rendered_title), title))
    for paragraph in certificate.rendered_body.split("\n\n"):
        story.append(Paragraph(escape(paragraph).replace("\n", "<br/>"), body))
        story.append(Spacer(1, 0.35 * cm))
    story.append(Spacer(1, 1.6 * cm))
    story.append(Table(
        [[_qr_image(verify_url, 2.6), Paragraph("<br/><br/><br/>Principal / Authorised Signatory", small)],
         [Paragraph("Scan to verify", small), ""]],
        colWidths=[8.3 * cm, 8.3 * cm],
        style=TableStyle([("ALIGN", (1, 0), (1, 0), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]),
    ))
    if certificate.is_revoked:
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph("<font color='red'><b>REVOKED</b></font>", title))
    doc.build(story)
    return buffer.getvalue()


def id_cards_pdf(students, valid_until=None):
    """A4 sheet of CR80-size (8.56 x 5.4 cm) ID cards, 2 x 5 per page.

    The QR carries the student's existing qr_token, the same payload the bus
    conductor scanner already reads (views/bus_tracking.py StudentIDQRView),
    so one printed card works for boarding too."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    import qrcode

    card_w, card_h = 8.56 * cm, 5.4 * cm
    margin_x, margin_y, gap = 1.4 * cm, 1.2 * cm, 0.5 * cm
    page_w, page_h = A4
    name = college_name()

    logo_reader = None
    logo = getattr(connection.tenant, "logo", None)
    if logo:
        try:
            with logo.open("rb") as handle:
                logo_reader = ImageReader(io.BytesIO(handle.read()))
        except Exception:
            logo_reader = None

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(f"ID cards: {name}")

    for index, student in enumerate(students):
        slot = index % 10
        if index and slot == 0:
            pdf.showPage()
        col, row = slot % 2, slot // 2
        x = margin_x + col * (card_w + gap)
        y = page_h - margin_y - (row + 1) * card_h - row * gap

        pdf.setStrokeColor(colors.HexColor("#1F3A5F"))
        pdf.roundRect(x, y, card_w, card_h, 0.25 * cm, stroke=1, fill=0)
        pdf.setFillColor(colors.HexColor("#1F3A5F"))
        pdf.rect(x, y + card_h - 1.0 * cm, card_w, 1.0 * cm, stroke=0, fill=1)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 8.5)
        text_x = x + 0.25 * cm
        if logo_reader is not None:
            pdf.drawImage(logo_reader, x + 0.15 * cm, y + card_h - 0.9 * cm, 0.8 * cm, 0.8 * cm,
                          preserveAspectRatio=True, mask="auto")
            text_x = x + 1.1 * cm
        pdf.drawString(text_x, y + card_h - 0.62 * cm, name[:48])

        # Photo
        photo_x, photo_y, photo_w, photo_h = x + 0.25 * cm, y + 0.9 * cm, 2.1 * cm, 2.6 * cm
        drew_photo = False
        if student.profile_picture:
            try:
                with student.profile_picture.open("rb") as handle:
                    pdf.drawImage(ImageReader(io.BytesIO(handle.read())), photo_x, photo_y, photo_w, photo_h,
                                  preserveAspectRatio=True, mask="auto")
                drew_photo = True
            except Exception:
                drew_photo = False
        if not drew_photo:
            pdf.setStrokeColor(colors.lightgrey)
            pdf.rect(photo_x, photo_y, photo_w, photo_h, stroke=1, fill=0)
            pdf.setFillColor(colors.grey)
            pdf.setFont("Helvetica", 6)
            pdf.drawCentredString(photo_x + photo_w / 2, photo_y + photo_h / 2, "PHOTO")

        # Details
        pdf.setFillColor(colors.black)
        detail_x = x + 2.6 * cm
        line_y = y + card_h - 1.5 * cm
        pdf.setFont("Helvetica-Bold", 8.5)
        pdf.drawString(detail_x, line_y, (student.user.get_full_name() or student.user.username)[:30])
        pdf.setFont("Helvetica", 7)
        rows = [
            ("ID", student.student_id),
            ("Dept", student.department.name if student.department else ""),
            ("Program", student.program_enrolled_in or ""),
            ("Batch", student.batch_academic_year or ""),
            ("Blood", student.blood_group or ""),
            ("Phone", student.emergency_contact_phone or student.contact_number or ""),
        ]
        for label, value in rows:
            line_y -= 0.36 * cm
            pdf.drawString(detail_x, line_y, f"{label}: {str(value)[:26]}")

        # QR
        qr_buffer = io.BytesIO()
        qrcode.make(str(student.qr_token), box_size=4, border=1).save(qr_buffer, format="PNG")
        qr_buffer.seek(0)
        qr_size = 1.7 * cm
        pdf.drawImage(ImageReader(qr_buffer), x + card_w - qr_size - 0.2 * cm, y + 0.2 * cm, qr_size, qr_size)

        pdf.setFont("Helvetica", 6)
        footer = f"Valid till {valid_until:%b %Y}" if valid_until else "Student identity card"
        pdf.drawString(x + 0.25 * cm, y + 0.35 * cm, footer)

    if not students:
        pdf.setFont("Helvetica", 11)
        pdf.drawString(margin_x, page_h - margin_y - cm, "No students matched the selection.")
    pdf.save()
    return buffer.getvalue()
