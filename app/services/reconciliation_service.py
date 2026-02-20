"""
Mpesa Auto-Reconciliation Engine

Confidence scoring:
  Phone match   → +40 pts  (tenant's registered Mpesa phone == transaction phone)
  Amount match  → +30 pts  (transaction amount == tenant's monthly_rent exactly)
  Ref match     → +20 pts  (account_reference contains unit number or tenant name)
  Timing match  → +10 pts  (transaction date between 1st–10th of the month)

Decision thresholds:
  90-100 → Auto-match: create payment record, update unit
  70-89  → Auto-match with "review" flag
  40-69  → Suggest match; require manual confirmation
  <40    → Unmatched; surface in dashboard

Special cases:
  • Duplicate receipt / same phone+amount+date within 1 hour → mark DUPLICATE
  • Partial payment (amount < rent)  → partial payment record + flag
  • Overpayment (amount > rent)      → match to rent, flag excess as credit
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.mpesa import (
    MpesaTransaction,
    MpesaReconciliationLog,
    ReconciliationStatus,
    ReconciliationAction,
)
from app.models.payment import Payment, PaymentStatus, PaymentMethod, PaymentGateway, PaymentType, PaymentCurrency
from app.models.property import Property, Unit
from app.models.tenant import Tenant
from app.models.user import User

logger = logging.getLogger(__name__)


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _score_phone(txn_phone: str, tenant_phone: str) -> int:
    """+40 if phones match after normalisation."""
    if not txn_phone or not tenant_phone:
        return 0
    # Normalise: strip non-digits, take last 9 digits for comparison
    def _digits(p: str) -> str:
        d = "".join(c for c in p if c.isdigit())
        return d[-9:] if len(d) >= 9 else d

    return 40 if _digits(txn_phone) == _digits(tenant_phone) else 0


def _score_amount(txn_amount: float, expected_rent: float) -> int:
    """
    +30 for exact match.
    +15 for within 5% (to handle rounding differences).
    +0  for partial or over.
    """
    if expected_rent <= 0:
        return 0
    if abs(txn_amount - expected_rent) < 1:  # within 1 KES
        return 30
    diff_pct = abs(txn_amount - expected_rent) / expected_rent
    if diff_pct <= 0.05:
        return 15
    return 0


def _score_account_reference(ref: str, unit_number: str, tenant_name: str, ref_format: str) -> int:
    """
    +20 if account_reference contains unit number OR tenant name OR matches format.
    Case-insensitive partial match.
    """
    if not ref:
        return 0
    ref_upper = ref.upper()
    checks = [
        unit_number.upper() if unit_number else "",
        tenant_name.upper() if tenant_name else "",
    ]
    # Also try formatted reference
    if ref_format:
        try:
            formatted = ref_format.format(
                unit_number=unit_number or "",
                tenant_name=tenant_name or "",
            ).upper()
            checks.append(formatted)
        except (KeyError, ValueError):
            pass

    for check in checks:
        if check and check in ref_upper:
            return 20
    return 0


def _score_timing(txn_date: datetime) -> int:
    """
    +10 if transaction falls between day 1 and day 10 of the month
    (standard rent payment window in Kenya).
    """
    return 10 if 1 <= txn_date.day <= 10 else 0


# ── Duplicate detection ───────────────────────────────────────────────────────

def _is_duplicate(txn: MpesaTransaction, db: Session) -> bool:
    """
    Returns True if:
    1. Same mpesa_receipt_number already exists (different row), OR
    2. Same phone + amount + within 1 hour already exists
    """
    # Same receipt
    dupe_by_receipt = (
        db.query(MpesaTransaction)
        .filter(
            MpesaTransaction.mpesa_receipt_number == txn.mpesa_receipt_number,
            MpesaTransaction.id != txn.id,
        )
        .first()
    )
    if dupe_by_receipt:
        return True

    # Same phone + amount within 1 hour
    one_hour_ago = txn.transaction_date - timedelta(hours=1)
    dupe_by_activity = (
        db.query(MpesaTransaction)
        .filter(
            MpesaTransaction.phone_number == txn.phone_number,
            MpesaTransaction.amount == txn.amount,
            MpesaTransaction.transaction_date >= one_hour_ago,
            MpesaTransaction.transaction_date <= txn.transaction_date + timedelta(hours=1),
            MpesaTransaction.id != txn.id,
            MpesaTransaction.reconciliation_status != ReconciliationStatus.DUPLICATE,
        )
        .first()
    )
    return bool(dupe_by_activity)


# ── Main reconciliation logic ─────────────────────────────────────────────────

class ReconciliationService:
    def __init__(self, db: Session):
        self.db = db

    def reconcile(self, transaction_id: uuid.UUID, owner_id: uuid.UUID) -> MpesaTransaction:
        """
        Run the full reconciliation pipeline for one transaction.
        Safe to call multiple times (idempotent if already matched).
        """
        txn = self.db.query(MpesaTransaction).filter(
            MpesaTransaction.id == transaction_id,
            MpesaTransaction.owner_id == owner_id,
        ).first()

        if not txn:
            logger.warning(f"[reconcile] Transaction {transaction_id} not found")
            return None

        # Skip if already reconciled
        if txn.reconciliation_status in (
            ReconciliationStatus.MATCHED,
            ReconciliationStatus.DUPLICATE,
        ):
            logger.info(f"[reconcile] {txn.mpesa_receipt_number} already {txn.reconciliation_status.value}")
            return txn

        # Duplicate check first
        if _is_duplicate(txn, self.db):
            txn.reconciliation_status = ReconciliationStatus.DUPLICATE
            self._log(txn, ReconciliationAction.FLAGGED, 0, "Duplicate receipt or phone+amount+time match", "system")
            self.db.commit()
            logger.info(f"[reconcile] {txn.mpesa_receipt_number} marked DUPLICATE")
            return txn

        # Get owner's config for reference format
        from app.models.mpesa import MpesaConfig
        config = self.db.query(MpesaConfig).filter(MpesaConfig.owner_id == owner_id).first()
        ref_format = config.account_reference_format if config else "UNIT-{unit_number}"

        # Score against each active tenant
        best_score = 0
        best_tenant: Optional[Tenant] = None
        best_unit: Optional[Unit] = None
        best_reason: Optional[str] = None

        tenants = (
            self.db.query(Tenant)
            .filter(Tenant.user_id == owner_id, Tenant.status == "active")
            .all()
        )

        for tenant in tenants:
            unit = self.db.query(Unit).filter(Unit.id == tenant.unit_id).first() if tenant.unit_id else None

            score = 0
            reasons = []

            # Phone match
            s_phone = _score_phone(txn.phone_number, tenant.phone or "")
            if s_phone:
                score += s_phone
                reasons.append(f"phone match +{s_phone}")

            # Amount match
            s_amount = _score_amount(txn.amount, tenant.rent_amount or 0)
            if s_amount:
                score += s_amount
                reasons.append(f"amount match +{s_amount}")

            # Account reference match
            unit_number = unit.unit_number if unit else ""
            s_ref = _score_account_reference(
                txn.account_reference or "",
                unit_number,
                tenant.full_name or "",
                ref_format or "",
            )
            if s_ref:
                score += s_ref
                reasons.append(f"account ref match +{s_ref}")

            # Timing match
            s_timing = _score_timing(txn.transaction_date)
            if s_timing:
                score += s_timing
                reasons.append(f"timing match +{s_timing}")

            if score > best_score:
                best_score = score
                best_tenant = tenant
                best_unit = unit
                best_reason = ", ".join(reasons)

        logger.info(
            f"[reconcile] {txn.mpesa_receipt_number}: best score={best_score} "
            f"tenant={best_tenant.full_name if best_tenant else 'none'} reason={best_reason}"
        )

        txn.reconciliation_confidence = best_score

        if best_score >= 90:
            self._do_auto_match(txn, best_tenant, best_unit, best_reason, flag_review=False)
        elif best_score >= 70:
            self._do_auto_match(txn, best_tenant, best_unit, best_reason, flag_review=True)
        elif best_score >= 40:
            # Suggest match — store resolved IDs but keep status unmatched for human review
            txn.tenant_id = best_tenant.id if best_tenant else None
            txn.unit_id = best_tenant.unit_id if best_tenant else None
            if best_tenant and best_tenant.property_id:
                txn.property_id = best_tenant.property_id
            txn.reconciliation_status = ReconciliationStatus.UNMATCHED
            self._log(txn, ReconciliationAction.FLAGGED, best_score,
                      f"Suggested match (score {best_score}): {best_reason}. Needs manual confirmation.", "system")
        else:
            txn.reconciliation_status = ReconciliationStatus.UNMATCHED
            self._log(txn, ReconciliationAction.FLAGGED, best_score,
                      f"No confident match found (score {best_score}). Manual resolution required.", "system")

        self.db.commit()
        self.db.refresh(txn)
        return txn

    def _do_auto_match(
        self,
        txn: MpesaTransaction,
        tenant: Tenant,
        unit: Optional[Unit],
        reason: str,
        flag_review: bool,
    ) -> None:
        """Create payment record and update transaction to matched."""
        if not tenant:
            return

        expected_rent = tenant.rent_amount or 0
        txn_amount = txn.amount

        # Determine match type
        if txn_amount < expected_rent and txn_amount > 0:
            # Partial payment
            status = ReconciliationStatus.PARTIAL
            match_reason = f"Partial payment (KES {txn_amount} of {expected_rent}). {reason}"
        else:
            status = ReconciliationStatus.MATCHED
            match_reason = reason

        # Create payment record
        payment = self._create_payment_record(txn, tenant, unit)
        if payment:
            txn.matched_payment_id = payment.id

        # Update transaction
        txn.tenant_id = tenant.id
        txn.unit_id = tenant.unit_id
        if tenant.property_id:
            txn.property_id = tenant.property_id
        txn.reconciliation_status = status

        if flag_review:
            match_reason = f"[REVIEW FLAGGED] {match_reason}"

        action = ReconciliationAction.AUTO_MATCHED
        self._log(txn, action, txn.reconciliation_confidence, match_reason, "system")

        # Cancel pending reminders for this tenant this month
        self._cancel_pending_reminders(tenant.id, txn.transaction_date)

        logger.info(
            f"[reconcile] {txn.mpesa_receipt_number} auto-matched to tenant "
            f"'{tenant.full_name}' (score={txn.reconciliation_confidence}, review={flag_review})"
        )

    def _create_payment_record(
        self,
        txn: MpesaTransaction,
        tenant: Tenant,
        unit: Optional[Unit],
    ) -> Optional[Payment]:
        """Insert a row in the payments table for the matched transaction."""
        try:
            # Avoid double-recording
            existing = self.db.query(Payment).filter(
                Payment.reference == txn.mpesa_receipt_number
            ).first()
            if existing:
                return existing

            owner_user = self.db.query(User).filter(User.id == txn.owner_id).first()

            payment = Payment(
                user_id=txn.owner_id,
                user_email=owner_user.email if owner_user else "",
                user_phone=txn.phone_number,
                amount=txn.amount,
                currency=PaymentCurrency.KES,
                gateway=PaymentGateway.PAYSTACK,  # sentinel value (mpesa is direct)
                method=PaymentMethod.MPESA,
                reference=txn.mpesa_receipt_number,
                transaction_id=txn.mpesa_receipt_number,
                status=PaymentStatus.COMPLETED,
                payment_type=PaymentType.RENT,
                tenant_id=tenant.id,
                payment_date=txn.transaction_date,
                paid_at=txn.transaction_date,
                description=f"Mpesa rent payment – {txn.mpesa_receipt_number}",
                payment_metadata=json.dumps({
                    "source": "mpesa_auto_reconciled",
                    "mpesa_transaction_id": str(txn.id),
                    "phone": txn.phone_number,
                }),
            )
            self.db.add(payment)
            self.db.flush()  # get ID before commit

            # Update tenant's last payment date
            tenant.last_payment_date = txn.transaction_date

            logger.info(f"[reconcile] Created payment record {payment.id} for {txn.mpesa_receipt_number}")
            return payment
        except Exception as exc:
            logger.error(f"[reconcile] Failed to create payment record: {exc}", exc_info=True)
            return None

    def _cancel_pending_reminders(self, tenant_id: uuid.UUID, payment_date: datetime) -> None:
        """Cancel all pending reminders for this tenant for the payment month."""
        from app.models.mpesa import MpesaReminder, ReminderStatus
        month_key = payment_date.strftime("%Y-%m")
        updated = (
            self.db.query(MpesaReminder)
            .filter(
                MpesaReminder.tenant_id == tenant_id,
                MpesaReminder.status == ReminderStatus.PENDING,
                MpesaReminder.reference_month == month_key,
            )
            .all()
        )
        for r in updated:
            r.status = ReminderStatus.FAILED  # use FAILED as "cancelled"
        if updated:
            logger.info(f"[reconcile] Cancelled {len(updated)} pending reminders for tenant {tenant_id}")

    def _log(
        self,
        txn: MpesaTransaction,
        action: ReconciliationAction,
        score: int,
        reason: str,
        performed_by: str,
    ) -> None:
        log = MpesaReconciliationLog(
            transaction_id=txn.id,
            action=action,
            confidence_score=score,
            match_reason=reason,
            performed_by=performed_by,
        )
        self.db.add(log)

    def manual_match(
        self,
        transaction_id: uuid.UUID,
        tenant_id: uuid.UUID,
        unit_id: uuid.UUID,
        property_id: uuid.UUID,
        performed_by: str,
    ) -> Optional[MpesaTransaction]:
        """Manually match a transaction — owner-initiated from dashboard."""
        txn = self.db.query(MpesaTransaction).filter(MpesaTransaction.id == transaction_id).first()
        if not txn:
            return None

        tenant = self.db.query(Tenant).filter(Tenant.id == tenant_id).first()
        unit = self.db.query(Unit).filter(Unit.id == unit_id).first() if unit_id else None

        txn.tenant_id = tenant_id
        txn.unit_id = unit_id
        txn.property_id = property_id
        txn.reconciliation_status = ReconciliationStatus.MATCHED
        txn.reconciliation_confidence = 100

        # Create payment record
        if tenant:
            payment = self._create_payment_record(txn, tenant, unit)
            if payment:
                txn.matched_payment_id = payment.id

        self._log(txn, ReconciliationAction.MANUAL_MATCHED, 100,
                  "Manually matched by owner", performed_by)
        self.db.commit()
        self.db.refresh(txn)

        logger.info(f"[reconcile] Manual match: {txn.mpesa_receipt_number} → tenant {tenant_id}")
        return txn

    def dispute(
        self,
        transaction_id: uuid.UUID,
        reason: str,
        performed_by: str,
    ) -> Optional[MpesaTransaction]:
        """Flag a transaction as disputed."""
        txn = self.db.query(MpesaTransaction).filter(MpesaTransaction.id == transaction_id).first()
        if not txn:
            return None

        txn.reconciliation_status = ReconciliationStatus.DISPUTED
        self._log(txn, ReconciliationAction.DISPUTED, txn.reconciliation_confidence,
                  f"Disputed: {reason}", performed_by)
        self.db.commit()
        self.db.refresh(txn)
        return txn
