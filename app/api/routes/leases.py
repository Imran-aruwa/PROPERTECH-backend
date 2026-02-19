"""
Digital Lease Management Routes
All protected endpoints use JWT auth; signing endpoints are public (token-based).

Authenticated (owner):
  GET    /api/leases/templates         – built-in clause templates
  GET    /api/leases/                  – list owner's leases
  POST   /api/leases/                  – create lease + clauses
  GET    /api/leases/{id}              – lease detail
  PUT    /api/leases/{id}              – update draft lease
  DELETE /api/leases/{id}             – delete draft lease
  POST   /api/leases/{id}/send        – generate signing token + email tenant
  POST   /api/leases/{id}/resend      – regenerate token + resend email
  GET    /api/leases/{id}/pdf         – return pdf_url (or trigger generation)

Public (no auth — token-based):
  GET    /api/leases/sign/{token}          – load lease for tenant review
  POST   /api/leases/sign/{token}          – submit signature + send OTP
  POST   /api/leases/sign/{token}/verify-otp – verify OTP → mark signed → gen PDF
  GET    /api/leases/{id}/pdf/download     – download the PDF file
"""
import io
import logging
import os
import uuid as uuid_module
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.lease import Lease, LeaseClause, LeaseSignature, LeaseStatus
from app.models.property import Property, Unit
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.lease import (
    ClauseTemplate, LeaseCreate, LeaseListItem, LeaseOut,
    LeaseUpdate, SendLeaseRequest, SignRequest, VerifyOtpRequest,
)
from app.services.lease_service import (
    generate_otp, hash_otp, otp_expiry, verify_otp,
    generate_lease_pdf, pdf_url_for_lease,
    send_signing_link_email, send_otp_email, send_signed_confirmation_email,
    resolve_tenant_info,
)

router = APIRouter(tags=["Leases"])
logger = logging.getLogger(__name__)

TOKEN_TTL_HOURS = 72


# ═══════════════════════ HELPERS ═══════════════════════

def _require_owner(current_user: User) -> None:
    if current_user.role not in [UserRole.OWNER, UserRole.AGENT, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Access denied")


def _get_lease_or_404(lease_id: UUID, owner_id, db: Session) -> Lease:
    lease = (
        db.query(Lease)
        .filter(Lease.id == lease_id, Lease.owner_id == owner_id)
        .first()
    )
    if not lease:
        raise HTTPException(status_code=404, detail="Lease not found")
    return lease


def _lease_to_out(lease: Lease, db: Session) -> dict:
    """Serialise a Lease ORM object to the dict shape LeaseOut expects."""

    def _fmt(dt) -> Optional[str]:
        if dt is None:
            return None
        if isinstance(dt, datetime):
            return dt.strftime("%Y-%m-%d")
        return str(dt)

    def _fmt_ts(dt) -> Optional[str]:
        if dt is None:
            return None
        return dt.isoformat()

    clauses = [
        {
            "id": str(c.id),
            "type": c.clause_type,
            "text": c.content,
            "editable": not c.is_required,
            "risk_weight": c.risk_weight or 0.0,
        }
        for c in sorted(lease.clauses, key=lambda x: x.order)
    ]

    signatures = [
        {
            "id": str(s.id),
            "lease_id": str(lease.id),
            "signer_name": s.signer_name,
            "signer_role": s.signer_role,
            "signature_type": s.signature_type,
            "signed_at": _fmt_ts(s.signed_at),
            "otp_verified": s.otp_verified,
            "ip_address": s.ip_address,
        }
        for s in lease.signatures
    ]

    # Attempt to enrich with property / unit / tenant objects
    prop = unit = tenant = None
    if lease.property_id:
        prop = db.query(Property).filter(Property.id == lease.property_id).first()
    if lease.unit_id:
        unit = db.query(Unit).filter(Unit.id == lease.unit_id).first()
    if lease.tenant_id:
        tenant = db.query(Tenant).filter(Tenant.id == lease.tenant_id).first()

    return {
        "id": str(lease.id),
        "owner_id": str(lease.owner_id),
        "property_id": str(lease.property_id) if lease.property_id else None,
        "unit_id": str(lease.unit_id) if lease.unit_id else None,
        "tenant_id": str(lease.tenant_id) if lease.tenant_id else None,
        "title": lease.title,
        "status": lease.status.value if hasattr(lease.status, "value") else str(lease.status),
        "start_date": _fmt(lease.start_date),
        "end_date": _fmt(lease.end_date),
        "rent_amount": lease.rent_amount,
        "deposit_amount": lease.deposit_amount,
        "payment_cycle": lease.payment_cycle.value if hasattr(lease.payment_cycle, "value") else str(lease.payment_cycle),
        "escalation_rate": lease.escalation_rate,
        "pdf_url": lease.pdf_url,
        "sent_at": _fmt_ts(lease.sent_at),
        "signed_at": _fmt_ts(lease.signed_at),
        "created_at": _fmt_ts(lease.created_at),
        "updated_at": _fmt_ts(lease.updated_at),
        "clauses": clauses,
        "signatures": signatures,
        "tenant_name": lease.tenant_name,
        "tenant_email": lease.tenant_email,
        "property": (
            {"id": str(prop.id), "name": prop.name, "address": prop.address}
            if prop else None
        ),
        "unit": (
            {"id": str(unit.id), "unit_number": unit.unit_number}
            if unit else None
        ),
        "tenant": (
            {
                "id": str(tenant.id) if tenant.id else None,
                "full_name": tenant.full_name,
                "email": tenant.email,
                "phone": tenant.phone,
            }
            if tenant
            else (
                {
                    "id": None,
                    "full_name": lease.tenant_name,
                    "email": lease.tenant_email,
                    "phone": lease.tenant_phone,
                }
                if lease.tenant_name
                else None
            )
        ),
    }


def _save_clauses(db: Session, lease: Lease, clauses_in) -> None:
    """Delete existing clauses and bulk-insert new ones."""
    for old in list(lease.clauses):
        db.delete(old)
    db.flush()
    for i, c in enumerate(clauses_in):
        cl = LeaseClause(
            id=uuid_module.uuid4(),
            lease_id=lease.id,
            clause_type=c.type if hasattr(c, "type") else c.get("type", "custom"),
            content=c.text if hasattr(c, "text") else c.get("text", ""),
            order=i,
            is_required=False,
            risk_weight=float(c.risk_weight or 0.0) if hasattr(c, "risk_weight") else 0.0,
        )
        db.add(cl)


# ═══════════════════════ BUILT-IN TEMPLATES ═══════════════════════

_CLAUSE_TEMPLATES = [
    ClauseTemplate(
        id="tpl_rent",
        type="rent",
        label="Rent Payment",
        text=(
            "The Tenant agrees to pay a monthly rent of KES [AMOUNT] on or before the 5th day "
            "of each calendar month. A late payment penalty of 10% of the monthly rent shall "
            "apply for payments received after the due date."
        ),
        editable=True,
        risk_weight=0.3,
    ),
    ClauseTemplate(
        id="tpl_deposit",
        type="custom",
        label="Security Deposit",
        text=(
            "The Tenant shall pay a refundable security deposit of KES [DEPOSIT] upon signing "
            "this agreement. The deposit shall be refunded within 30 days of the lease end date, "
            "less any deductions for damages or unpaid rent."
        ),
        editable=True,
        risk_weight=0.2,
    ),
    ClauseTemplate(
        id="tpl_termination",
        type="termination",
        label="Termination",
        text=(
            "Either party may terminate this lease by providing at least one (1) calendar month's "
            "written notice to the other party. Early termination by the Tenant without notice "
            "shall result in forfeiture of the security deposit."
        ),
        editable=True,
        risk_weight=0.25,
    ),
    ClauseTemplate(
        id="tpl_maintenance",
        type="maintenance",
        label="Maintenance",
        text=(
            "The Tenant is responsible for minor repairs up to KES 5,000. The Landlord is "
            "responsible for structural repairs and major appliance maintenance. The Tenant must "
            "report any damage or maintenance issues within 48 hours of discovery."
        ),
        editable=True,
        risk_weight=0.15,
    ),
    ClauseTemplate(
        id="tpl_pets",
        type="pets",
        label="Pets Policy",
        text=(
            "No pets are permitted on the premises without prior written consent from the Landlord. "
            "Violation of this clause may result in immediate termination of the lease."
        ),
        editable=True,
        risk_weight=0.05,
    ),
    ClauseTemplate(
        id="tpl_utilities",
        type="utilities",
        label="Utilities",
        text=(
            "The Tenant is responsible for payment of all utilities including water, electricity, "
            "and internet. The Landlord shall cover rates and taxes on the property."
        ),
        editable=True,
        risk_weight=0.05,
    ),
]


# ═══════════════════════ ROUTES ═══════════════════════

# ── Static routes first (before /{lease_id}) ──────────────────────

@router.get("/templates", response_model=List[ClauseTemplate])
def get_clause_templates(
    current_user: User = Depends(get_current_user),
):
    """Return the 6 built-in clause templates (matching app/lib/lease-templates.ts)."""
    _require_owner(current_user)
    return _CLAUSE_TEMPLATES


@router.get("/", response_model=List[dict])
def list_leases(
    status: Optional[str] = Query(None),
    property_id: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all leases belonging to the authenticated owner."""
    _require_owner(current_user)

    q = db.query(Lease).filter(Lease.owner_id == current_user.id)

    if status:
        try:
            q = q.filter(Lease.status == LeaseStatus(status))
        except ValueError:
            pass

    if property_id:
        try:
            q = q.filter(Lease.property_id == uuid_module.UUID(property_id))
        except ValueError:
            pass

    if tenant_id:
        try:
            q = q.filter(Lease.tenant_id == uuid_module.UUID(tenant_id))
        except ValueError:
            pass

    leases = q.order_by(Lease.created_at.desc()).offset(skip).limit(limit).all()
    return [_lease_to_out(l, db) for l in leases]


@router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_lease(
    payload: LeaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new lease in DRAFT status with clauses."""
    _require_owner(current_user)

    # Parse dates
    try:
        start = datetime.strptime(payload.start_date[:10], "%Y-%m-%d")
        end = datetime.strptime(payload.end_date[:10], "%Y-%m-%d")
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid date format: {e}")

    if end <= start:
        raise HTTPException(status_code=422, detail="end_date must be after start_date")

    # Resolve tenant / property / unit — IDs may all be None from the frontend
    tenant, prop, unit = resolve_tenant_info(
        db,
        owner_id=current_user.id,
        tenant_id=payload.tenant_id,
        unit_id=payload.unit_id,
        property_id=payload.property_id,
        rent_amount=payload.rent_amount,
    )

    # Derive display title
    tenant_display = (tenant.full_name if tenant else None) or "Tenant"
    title = f"Lease Agreement — {tenant_display} ({start.strftime('%b %Y')} – {end.strftime('%b %Y')})"

    lease = Lease(
        id=uuid_module.uuid4(),
        owner_id=current_user.id,
        property_id=prop.id if prop else payload.property_id,
        unit_id=unit.id if unit else payload.unit_id,
        tenant_id=tenant.id if tenant else payload.tenant_id,
        title=title,
        status=LeaseStatus.DRAFT,
        start_date=start,
        end_date=end,
        rent_amount=payload.rent_amount,
        deposit_amount=payload.deposit_amount,
        payment_cycle=payload.payment_cycle or "monthly",
        escalation_rate=payload.escalation_rate,
        tenant_name=tenant.full_name if tenant else None,
        tenant_email=tenant.email if tenant else None,
        tenant_phone=tenant.phone if tenant else None,
    )
    db.add(lease)
    db.flush()

    # Save clauses
    _save_clauses(db, lease, payload.clauses)

    db.commit()
    db.refresh(lease)

    logger.info(
        f"[LEASE] Created lease {lease.id} for owner {current_user.id} "
        f"(tenant: {lease.tenant_name or 'unknown'})"
    )
    return _lease_to_out(lease, db)


@router.get("/sign/{token}")
def get_lease_for_signing(
    token: str,
    db: Session = Depends(get_db),
):
    """
    PUBLIC — Load the lease for tenant review.
    Validates that the signing token exists and has not expired.
    """
    try:
        token_uuid = uuid_module.UUID(token)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid signing token")

    lease = db.query(Lease).filter(Lease.signing_token == token_uuid).first()

    if not lease:
        raise HTTPException(status_code=404, detail="Invalid or expired signing link")

    if lease.token_expires_at and lease.token_expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=410, detail="This signing link has expired. Please request a new one."
        )

    if lease.status == LeaseStatus.SIGNED:
        raise HTTPException(
            status_code=409, detail="This lease has already been signed."
        )

    return _lease_to_out(lease, db)


@router.post("/sign/{token}")
def submit_signature(
    token: str,
    payload: SignRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    PUBLIC — Submit tenant's signature and send OTP for verification.
    On resend=True, re-uses the existing signature record and resends the OTP.
    """
    try:
        token_uuid = uuid_module.UUID(token)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid signing token")

    lease = db.query(Lease).filter(Lease.signing_token == token_uuid).first()
    if not lease:
        raise HTTPException(status_code=404, detail="Invalid or expired signing link")

    if lease.token_expires_at and lease.token_expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Signing link has expired")

    if lease.status == LeaseStatus.SIGNED:
        raise HTTPException(status_code=409, detail="Lease already signed")

    # Resolve client IP
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or request.headers.get("x-real-ip")
        or (request.client.host if request.client else None)
    )

    otp = generate_otp()
    otp_hash = hash_otp(otp)
    expiry = otp_expiry()

    if payload.resend:
        # Re-use existing signature record — just refresh OTP
        sig = (
            db.query(LeaseSignature)
            .filter(
                LeaseSignature.lease_id == lease.id,
                LeaseSignature.otp_verified == False,  # noqa: E712
            )
            .first()
        )
        if not sig:
            raise HTTPException(status_code=400, detail="No pending signature to resend OTP for")
        sig.otp_code_hash = otp_hash
        sig.otp_expires_at = expiry
        sig.otp_attempts = 0
    else:
        # Remove any unverified signatures and create a fresh one
        db.query(LeaseSignature).filter(
            LeaseSignature.lease_id == lease.id,
            LeaseSignature.otp_verified == False,  # noqa: E712
        ).delete()

        sig = LeaseSignature(
            id=uuid_module.uuid4(),
            lease_id=lease.id,
            signer_name=payload.signer_name or lease.tenant_name or "Tenant",
            signer_email=lease.tenant_email,
            signer_phone=lease.tenant_phone,
            signer_role="tenant",
            signature_type=payload.signature_type,
            signature_data=payload.signature_data,
            otp_code_hash=otp_hash,
            otp_expires_at=expiry,
            otp_verified=False,
            otp_attempts=0,
            ip_address=payload.ip_address or client_ip,
            device_fingerprint=payload.device_fingerprint,
        )
        db.add(sig)

    db.commit()

    # Send OTP via email
    to_email = lease.tenant_email
    tenant_name = (
        payload.signer_name or lease.tenant_name or "Tenant"
    )

    if to_email:
        try:
            send_otp_email(to_email, tenant_name, otp, lease.title)
        except Exception as email_err:
            logger.warning(f"[LEASE][OTP_EMAIL] Failed: {email_err}")
    else:
        logger.warning(
            f"[LEASE] No tenant email for lease {lease.id} — OTP not sent. OTP={otp}"
        )

    return {"success": True, "message": "Verification code sent to your email"}


@router.post("/sign/{token}/verify-otp")
def verify_otp_endpoint(
    token: str,
    payload: VerifyOtpRequest,
    db: Session = Depends(get_db),
):
    """
    PUBLIC — Verify the OTP, mark lease as signed, generate PDF, notify owner.
    """
    try:
        token_uuid = uuid_module.UUID(token)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid signing token")

    lease = db.query(Lease).filter(Lease.signing_token == token_uuid).first()
    if not lease:
        raise HTTPException(status_code=404, detail="Invalid signing link")

    if lease.status == LeaseStatus.SIGNED:
        raise HTTPException(status_code=409, detail="Lease already signed")

    sig = (
        db.query(LeaseSignature)
        .filter(
            LeaseSignature.lease_id == lease.id,
            LeaseSignature.otp_verified == False,  # noqa: E712
        )
        .first()
    )
    if not sig:
        raise HTTPException(
            status_code=400,
            detail="No pending signature found. Please submit your signature first.",
        )

    # Check expiry
    if sig.otp_expires_at and sig.otp_expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="OTP has expired. Please request a new one.")

    # Rate-limit OTP attempts
    sig.otp_attempts = (sig.otp_attempts or 0) + 1
    if sig.otp_attempts > 5:
        db.commit()
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Please restart the signing process.",
        )

    if not verify_otp(payload.otp.strip(), sig.otp_code_hash):
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid verification code")

    # Mark OTP verified
    now = datetime.utcnow()
    sig.otp_verified = True
    sig.signed_at = now
    sig.otp_code_hash = None   # Clear hash after use

    # Update lease status
    lease.status = LeaseStatus.SIGNED
    lease.signed_at = now
    lease.signing_token = None    # Invalidate token so link cannot be reused
    lease.token_expires_at = None

    # Also update the linked Tenant record if we have a tenant_id
    if lease.tenant_id:
        try:
            from app.models.tenant import Tenant
            tenant_rec = db.query(Tenant).filter(Tenant.id == lease.tenant_id).first()
            if tenant_rec:
                # Store signed PDF URL on tenant record for backward compat
                tenant_rec.lease_agreement_url = lease.pdf_url or ""
        except Exception:
            pass

    db.commit()

    # Generate PDF asynchronously-ish (blocking but fast with reportlab)
    pdf_path = generate_lease_pdf(lease, lease.clauses, sig)
    pdf_url = None
    if pdf_path:
        pdf_url = pdf_url_for_lease(str(lease.id))
        lease.pdf_url = pdf_url
        if lease.tenant_id:
            try:
                from app.models.tenant import Tenant
                t = db.query(Tenant).filter(Tenant.id == lease.tenant_id).first()
                if t:
                    t.lease_agreement_url = pdf_url
            except Exception:
                pass
        db.commit()

    # Notify owner
    try:
        owner = db.query(User).filter(User.id == lease.owner_id).first()
        if owner and owner.email:
            send_signed_confirmation_email(
                owner.email,
                owner.full_name or owner.email,
                sig.signer_name,
                lease.title,
                pdf_url,
            )
    except Exception as notif_err:
        logger.warning(f"[LEASE] Owner notification failed: {notif_err}")

    return {
        "success": True,
        "message": "Lease signed successfully",
        "pdf_url": pdf_url,
    }


# ── Authenticated routes (owner) ──────────────────────────────────

@router.get("/{lease_id}", response_model=dict)
def get_lease(
    lease_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single lease with full detail."""
    _require_owner(current_user)
    lease = _get_lease_or_404(lease_id, current_user.id, db)
    return _lease_to_out(lease, db)


@router.put("/{lease_id}", response_model=dict)
def update_lease(
    lease_id: UUID,
    payload: LeaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a lease. Only DRAFT and SENT leases can be edited."""
    _require_owner(current_user)
    lease = _get_lease_or_404(lease_id, current_user.id, db)

    if lease.status not in [LeaseStatus.DRAFT, LeaseStatus.SENT]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot edit a lease in '{lease.status}' status",
        )

    update_data = payload.dict(exclude_unset=True)

    if "start_date" in update_data:
        try:
            lease.start_date = datetime.strptime(update_data.pop("start_date")[:10], "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid start_date")

    if "end_date" in update_data:
        try:
            lease.end_date = datetime.strptime(update_data.pop("end_date")[:10], "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid end_date")

    if "clauses" in update_data:
        _save_clauses(db, lease, update_data.pop("clauses"))

    for key, value in update_data.items():
        setattr(lease, key, value)

    db.commit()
    db.refresh(lease)
    return _lease_to_out(lease, db)


@router.delete("/{lease_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lease(
    lease_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a lease. Only DRAFT leases can be deleted."""
    _require_owner(current_user)
    lease = _get_lease_or_404(lease_id, current_user.id, db)

    if lease.status not in [LeaseStatus.DRAFT]:
        raise HTTPException(
            status_code=400,
            detail="Only draft leases can be deleted",
        )

    db.delete(lease)
    db.commit()
    return None


@router.post("/{lease_id}/send")
def send_lease(
    lease_id: UUID,
    payload: SendLeaseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a signing token, set lease status → sent,
    and email the signing link to the tenant.
    """
    _require_owner(current_user)
    lease = _get_lease_or_404(lease_id, current_user.id, db)

    if lease.status == LeaseStatus.SIGNED:
        raise HTTPException(status_code=400, detail="Lease is already signed")

    # Generate fresh signing token
    token = uuid_module.uuid4()
    lease.signing_token = token
    lease.token_expires_at = datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS)
    lease.status = LeaseStatus.SENT
    lease.sent_at = datetime.utcnow()
    db.commit()

    # Build signing URL
    try:
        from app.core.config import settings
        frontend_url = settings.FRONTEND_URL.rstrip("/")
    except Exception:
        frontend_url = os.getenv("FRONTEND_URL", "https://propertechsoftware.com")

    signing_url = f"{frontend_url}/sign/{token}"

    # Resolve tenant email — try lease denorm, then DB lookup
    to_email = lease.tenant_email
    tenant_name = lease.tenant_name or "Tenant"

    if not to_email and lease.tenant_id:
        try:
            t = db.query(Tenant).filter(Tenant.id == lease.tenant_id).first()
            if t:
                to_email = t.email
                tenant_name = t.full_name or tenant_name
        except Exception:
            pass

    # Get owner name for email
    owner_name = current_user.full_name or current_user.email or "Your Landlord"

    email_sent = False
    if "email" in payload.channels and to_email:
        try:
            email_sent = send_signing_link_email(
                to_email, tenant_name, lease.title, signing_url, owner_name
            )
        except Exception as email_err:
            logger.warning(f"[LEASE][SEND] Email dispatch failed: {email_err}")

    logger.info(
        f"[LEASE] Sent lease {lease.id} | token={token} | "
        f"email_sent={email_sent} | to={to_email or 'unknown'}"
    )

    return {
        "success": True,
        "message": "Signing link generated" + (" and emailed to tenant" if email_sent else " (email not configured or tenant email not found)"),
        "signing_url": signing_url,
        "token_expires_at": lease.token_expires_at.isoformat(),
        "email_sent": email_sent,
    }


@router.post("/{lease_id}/resend")
def resend_lease(
    lease_id: UUID,
    payload: SendLeaseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Regenerate signing token and resend email to tenant."""
    _require_owner(current_user)
    lease = _get_lease_or_404(lease_id, current_user.id, db)

    if lease.status == LeaseStatus.SIGNED:
        raise HTTPException(status_code=400, detail="Lease is already signed")

    # Delegate to send logic
    return send_lease(
        lease_id=lease_id,
        payload=payload,
        db=db,
        current_user=current_user,
    )


@router.get("/{lease_id}/pdf")
def get_lease_pdf(
    lease_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the PDF URL, or trigger generation if missing."""
    _require_owner(current_user)
    lease = _get_lease_or_404(lease_id, current_user.id, db)

    if lease.pdf_url:
        return {"success": True, "pdf_url": lease.pdf_url}

    # Try generating on demand for signed leases
    if lease.status == LeaseStatus.SIGNED:
        sig = (
            db.query(LeaseSignature)
            .filter(
                LeaseSignature.lease_id == lease.id,
                LeaseSignature.otp_verified == True,  # noqa: E712
            )
            .first()
        )
        pdf_path = generate_lease_pdf(lease, lease.clauses, sig)
        if pdf_path:
            pdf_url = pdf_url_for_lease(str(lease.id))
            lease.pdf_url = pdf_url
            db.commit()
            return {"success": True, "pdf_url": pdf_url}

    return {"success": False, "pdf_url": None, "message": "PDF not yet available"}


@router.get("/{lease_id}/pdf/download")
def download_lease_pdf(
    lease_id: UUID,
    db: Session = Depends(get_db),
):
    """
    PUBLIC — Serve the PDF file directly.
    The URL is returned after OTP verification so the tenant can also download it.
    """
    from app.services.lease_service import _PDF_DIR

    filename = f"lease_{lease_id}.pdf"
    filepath = _PDF_DIR / filename

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="PDF not found or not yet generated")

    return FileResponse(
        path=str(filepath),
        media_type="application/pdf",
        filename=filename,
    )
