"""
Lease Service — Email dispatch, OTP generation, PDF generation.
All I/O-heavy operations are isolated here so routes stay thin.
"""
import io
import logging
import os
import random
import secrets
import smtplib
import string
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from passlib.context import CryptContext
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ─────────────────────── OTP ───────────────────────

_otp_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
OTP_TTL_MINUTES = 10
MAX_OTP_ATTEMPTS = 5


def generate_otp() -> str:
    """Return a 6-digit numeric OTP."""
    return "".join(random.choices(string.digits, k=6))


def hash_otp(otp: str) -> str:
    return _otp_ctx.hash(otp)


def verify_otp(plain: str, hashed: str) -> bool:
    try:
        return _otp_ctx.verify(plain, hashed)
    except Exception:
        return False


def otp_expiry() -> datetime:
    return datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)


# ─────────────────────── Email ───────────────────────

def _smtp_settings():
    """Read SMTP settings — prefer Settings class, fall back to env vars."""
    try:
        from app.core.config import settings
        host = settings.SMTP_SERVER
        port = settings.SMTP_PORT
        user = settings.SMTP_USER
        pwd  = settings.SMTP_PASSWORD
        frm  = settings.EMAIL_FROM
    except Exception:
        host = os.getenv("SMTP_SERVER", os.getenv("SMTP_HOST", ""))
        port = int(os.getenv("SMTP_PORT", "587"))
        user = os.getenv("SMTP_USER", "")
        pwd  = os.getenv("SMTP_PASSWORD", os.getenv("SMTP_PASS", ""))
        frm  = os.getenv("EMAIL_FROM", user or "noreply@propertech.app")
    return host, port, user, pwd, frm


def send_email(to: str, subject: str, body_html: str, body_text: str = "") -> bool:
    """
    Dispatch a transactional email via SMTP.
    Returns True on success, False if SMTP is not configured (logs warning).
    """
    host, port, user, pwd, frm = _smtp_settings()

    if not host or not user or not pwd:
        logger.warning(
            f"[LEASE][EMAIL] SMTP not configured. Would send to '{to}': {subject}"
        )
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = frm
        msg["To"] = to
        if body_text:
            msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(host, port, timeout=10) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(user, pwd)
            srv.sendmail(frm, to, msg.as_string())

        logger.info(f"[LEASE][EMAIL] Sent to '{to}': {subject}")
        return True
    except Exception as exc:
        logger.error(f"[LEASE][EMAIL] Failed sending to '{to}': {exc}")
        return False


def send_signing_link_email(
    to_email: str,
    tenant_name: str,
    lease_title: str,
    signing_url: str,
    owner_name: str = "Your Landlord",
) -> bool:
    subject = f"Please sign your lease — {lease_title}"
    html = f"""
<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#333">
  <div style="background:#2563eb;padding:20px;border-radius:8px 8px 0 0;text-align:center">
    <h1 style="color:#fff;margin:0;font-size:22px">Propertech</h1>
  </div>
  <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;padding:30px;border-radius:0 0 8px 8px">
    <p>Hi <strong>{tenant_name}</strong>,</p>
    <p><strong>{owner_name}</strong> has sent you a lease agreement for your review and signature.</p>
    <p style="font-weight:600">{lease_title}</p>
    <p>Please click the button below to review the terms and sign digitally. The link expires in <strong>72 hours</strong>.</p>
    <div style="text-align:center;margin:30px 0">
      <a href="{signing_url}"
         style="background:#2563eb;color:#fff;padding:14px 32px;border-radius:8px;
                text-decoration:none;font-weight:600;font-size:15px;display:inline-block">
        Review &amp; Sign Lease
      </a>
    </div>
    <p style="color:#6b7280;font-size:13px">
      If the button doesn't work, copy and paste this link into your browser:<br>
      <a href="{signing_url}" style="color:#2563eb">{signing_url}</a>
    </p>
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0">
    <p style="color:#9ca3af;font-size:12px">
      This email was sent by Propertech on behalf of {owner_name}.
      If you were not expecting this, please contact your landlord directly.
    </p>
  </div>
</body>
</html>"""
    text = (
        f"Hi {tenant_name},\n\n"
        f"{owner_name} has sent you a lease agreement: {lease_title}\n\n"
        f"Please review and sign at:\n{signing_url}\n\n"
        "This link expires in 72 hours.\n\n— Propertech"
    )
    return send_email(to_email, subject, html, text)


def send_otp_email(
    to_email: str,
    tenant_name: str,
    otp: str,
    lease_title: str,
) -> bool:
    subject = f"Your signing verification code — {otp}"
    html = f"""
<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#333">
  <div style="background:#2563eb;padding:20px;border-radius:8px 8px 0 0;text-align:center">
    <h1 style="color:#fff;margin:0;font-size:22px">Propertech</h1>
  </div>
  <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;padding:30px;border-radius:0 0 8px 8px">
    <p>Hi <strong>{tenant_name}</strong>,</p>
    <p>Your verification code for signing <strong>{lease_title}</strong> is:</p>
    <div style="text-align:center;margin:24px 0">
      <span style="font-size:42px;font-weight:700;letter-spacing:12px;
                   color:#1d4ed8;background:#eff6ff;padding:16px 24px;
                   border-radius:8px;display:inline-block">{otp}</span>
    </div>
    <p>This code expires in <strong>10 minutes</strong>. Do not share it with anyone.</p>
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0">
    <p style="color:#9ca3af;font-size:12px">If you did not request this code, please ignore this email.</p>
  </div>
</body>
</html>"""
    text = (
        f"Hi {tenant_name},\n\n"
        f"Your verification code for signing '{lease_title}' is: {otp}\n\n"
        "This code expires in 10 minutes. Do not share it with anyone.\n\n— Propertech"
    )
    return send_email(to_email, subject, html, text)


def send_signed_confirmation_email(
    owner_email: str,
    owner_name: str,
    tenant_name: str,
    lease_title: str,
    pdf_url: Optional[str],
) -> bool:
    subject = f"Lease signed — {tenant_name}"
    pdf_line = (
        f'<p><a href="{pdf_url}" style="color:#2563eb">Download signed PDF</a></p>'
        if pdf_url
        else ""
    )
    html = f"""
<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#333">
  <div style="background:#059669;padding:20px;border-radius:8px 8px 0 0;text-align:center">
    <h1 style="color:#fff;margin:0;font-size:22px">Lease Signed</h1>
  </div>
  <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;padding:30px;border-radius:0 0 8px 8px">
    <p>Hi <strong>{owner_name}</strong>,</p>
    <p><strong>{tenant_name}</strong> has successfully signed the lease:</p>
    <p style="font-weight:600">{lease_title}</p>
    {pdf_line}
    <p>The lease status has been updated to <strong>Signed</strong> in your dashboard.</p>
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0">
    <p style="color:#9ca3af;font-size:12px">Propertech — Digital Lease Management</p>
  </div>
</body>
</html>"""
    text = (
        f"Hi {owner_name},\n\n"
        f"{tenant_name} has signed '{lease_title}'.\n\n"
        + (f"Download PDF: {pdf_url}\n\n" if pdf_url else "")
        + "— Propertech"
    )
    return send_email(owner_email, subject, html, text)


# ─────────────────────── PDF ───────────────────────

_PDF_DIR = Path(os.getenv("LEASE_PDF_DIR", "/tmp/leases"))


def _ensure_pdf_dir():
    _PDF_DIR.mkdir(parents=True, exist_ok=True)


def generate_lease_pdf(lease, clauses, signature) -> Optional[str]:
    """
    Generate a PDF for a signed lease using reportlab.
    Returns the file path (relative URL) or None on failure.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        )
    except ImportError:
        logger.error("[LEASE][PDF] reportlab not installed. Run: pip install reportlab")
        return None

    try:
        _ensure_pdf_dir()
        filename = f"lease_{lease.id}.pdf"
        filepath = _PDF_DIR / filename

        doc = SimpleDocTemplate(
            str(filepath),
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "Title",
            parent=styles["Heading1"],
            fontSize=18,
            spaceAfter=12,
            textColor=colors.HexColor("#1d4ed8"),
        )
        h2_style = ParagraphStyle(
            "H2",
            parent=styles["Heading2"],
            fontSize=13,
            spaceBefore=14,
            spaceAfter=6,
            textColor=colors.HexColor("#374151"),
        )
        body_style = styles["BodyText"]
        body_style.spaceAfter = 6
        small_style = ParagraphStyle(
            "Small",
            parent=styles["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#6b7280"),
        )

        story = []

        # Title
        story.append(Paragraph("LEASE AGREEMENT", title_style))
        story.append(Paragraph(lease.title or "Lease Agreement", styles["Heading2"]))
        story.append(Spacer(1, 0.4 * cm))

        # Parties & terms table
        signed_date = (
            signature.signed_at.strftime("%d %B %Y %H:%M UTC")
            if signature and signature.signed_at
            else "—"
        )
        terms = [
            ["Field", "Details"],
            ["Tenant", lease.tenant_name or "—"],
            ["Tenant Email", lease.tenant_email or "—"],
            ["Start Date", lease.start_date.strftime("%d %B %Y") if lease.start_date else "—"],
            ["End Date", lease.end_date.strftime("%d %B %Y") if lease.end_date else "—"],
            ["Monthly Rent", f"KES {lease.rent_amount:,.0f}"],
            ["Deposit", f"KES {lease.deposit_amount:,.0f}"],
            ["Payment Cycle", lease.payment_cycle.value if hasattr(lease.payment_cycle, 'value') else str(lease.payment_cycle)],
            ["Escalation Rate", f"{lease.escalation_rate}%" if lease.escalation_rate else "None"],
            ["Status", "SIGNED"],
            ["Signed At", signed_date],
        ]
        tbl = Table(terms, colWidths=[5 * cm, 12 * cm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f9fafb")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 0.6 * cm))

        # Clauses
        story.append(Paragraph("TERMS AND CONDITIONS", h2_style))
        for i, clause in enumerate(clauses, 1):
            clause_type = clause.clause_type if hasattr(clause, 'clause_type') else clause.get('type', 'custom')
            content = clause.content if hasattr(clause, 'content') else clause.get('text', '')
            story.append(Paragraph(f"{i}. {clause_type.upper()}", styles["Heading3"]))
            story.append(Paragraph(content, body_style))
            story.append(Spacer(1, 0.2 * cm))

        # Signature block
        story.append(Spacer(1, 0.8 * cm))
        story.append(Paragraph("SIGNATURE", h2_style))

        if signature:
            sig_data = [
                ["Signer Name", signature.signer_name or "—"],
                ["Signature Type", signature.signature_type.upper()],
                ["OTP Verified", "YES" if signature.otp_verified else "NO"],
                ["IP Address", signature.ip_address or "—"],
                ["Signed At", signed_date],
            ]
            sig_tbl = Table(sig_data, colWidths=[5 * cm, 12 * cm])
            sig_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdf4")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1fae5")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(sig_tbl)

            # Embed drawn signature image if available
            if signature.signature_type == "drawn" and signature.signature_data:
                try:
                    import base64
                    from reportlab.platypus import Image as RLImage
                    img_data = base64.b64decode(
                        signature.signature_data.split(",")[-1]
                    )
                    img_buf = io.BytesIO(img_data)
                    img = RLImage(img_buf, width=6 * cm, height=2 * cm)
                    story.append(Spacer(1, 0.4 * cm))
                    story.append(img)
                except Exception as img_err:
                    logger.warning(f"[LEASE][PDF] Could not embed signature image: {img_err}")
            elif signature.signature_type == "typed":
                story.append(Spacer(1, 0.4 * cm))
                story.append(
                    Paragraph(
                        f'<i style="font-family:Times-Italic;font-size:20">{signature.signature_data}</i>',
                        ParagraphStyle(
                            "Sig",
                            parent=styles["Normal"],
                            fontSize=18,
                            fontName="Times-Italic",
                            textColor=colors.HexColor("#1e40af"),
                        ),
                    )
                )

        # Footer
        story.append(Spacer(1, 1 * cm))
        story.append(
            Paragraph(
                f"Generated by Propertech on {datetime.utcnow().strftime('%d %B %Y %H:%M UTC')} — "
                "This document is legally binding once signed and OTP-verified.",
                small_style,
            )
        )

        doc.build(story)
        logger.info(f"[LEASE][PDF] Generated: {filepath}")
        return str(filepath)

    except Exception as exc:
        logger.error(f"[LEASE][PDF] Generation failed: {exc}")
        return None


def pdf_url_for_lease(lease_id: str) -> str:
    """Return the public URL path for the lease PDF."""
    return f"/api/leases/{lease_id}/pdf/download"


# ─────────────────────── Tenant resolution ───────────────────────

def resolve_tenant_info(
    db: Session,
    owner_id,
    tenant_id=None,
    unit_id=None,
    property_id=None,
    rent_amount: Optional[float] = None,
):
    """
    Try to find the tenant linked to this lease from the DB.
    Returns (tenant_obj | None, property_obj | None, unit_obj | None).

    Resolution order:
      1. tenant_id FK lookup
      2. unit_id → active tenant for that unit
      3. property_id → most recent active tenant for any unit in that property
      4. rent_amount match among owner's active tenants
      5. owner's most recent single active tenant (last resort)
    """
    from app.models.tenant import Tenant
    from app.models.property import Property, Unit
    from app.models.user import User

    tenant = prop = unit = None

    try:
        # 1. Direct tenant_id
        if tenant_id:
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()

        # 2. Via unit_id
        if not tenant and unit_id:
            unit = db.query(Unit).filter(Unit.id == unit_id).first()
            if unit:
                tenant = (
                    db.query(Tenant)
                    .filter(Tenant.unit_id == unit_id, Tenant.status == "active")
                    .order_by(Tenant.created_at.desc())
                    .first()
                )

        # 3. Via property_id
        if not tenant and property_id:
            prop = db.query(Property).filter(Property.id == property_id).first()
            if prop:
                tenant = (
                    db.query(Tenant)
                    .filter(Tenant.property_id == property_id, Tenant.status == "active")
                    .order_by(Tenant.created_at.desc())
                    .first()
                )

        # 4. Rent amount match across owner's properties
        if not tenant and rent_amount:
            owner_prop_ids = [
                r[0]
                for r in db.query(Property.id)
                .filter(Property.user_id == owner_id)
                .all()
            ]
            if owner_prop_ids:
                candidates = (
                    db.query(Tenant)
                    .filter(
                        Tenant.property_id.in_(owner_prop_ids),
                        Tenant.status == "active",
                        Tenant.rent_amount == rent_amount,
                    )
                    .all()
                )
                if len(candidates) == 1:
                    tenant = candidates[0]

        # 5. Last-resort: owner's single active tenant
        if not tenant:
            owner_prop_ids = [
                r[0]
                for r in db.query(Property.id)
                .filter(Property.user_id == owner_id)
                .all()
            ]
            if owner_prop_ids:
                all_active = (
                    db.query(Tenant)
                    .filter(
                        Tenant.property_id.in_(owner_prop_ids),
                        Tenant.status == "active",
                    )
                    .order_by(Tenant.created_at.desc())
                    .all()
                )
                if len(all_active) == 1:
                    tenant = all_active[0]

        # Resolve property / unit from tenant if needed
        if tenant:
            if not unit and tenant.unit_id:
                unit = db.query(Unit).filter(Unit.id == tenant.unit_id).first()
            if not prop and tenant.property_id:
                prop = db.query(Property).filter(Property.id == tenant.property_id).first()

    except Exception as exc:
        logger.warning(f"[LEASE][RESOLVE] Could not resolve tenant: {exc}")

    return tenant, prop, unit
