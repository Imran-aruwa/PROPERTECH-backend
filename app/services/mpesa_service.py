"""
Mpesa Payment Intelligence Engine — Daraja API Service

Covers:
  • OAuth 2.0 token management (cached with TTL)
  • STK Push (Lipa Na Mpesa Online)
  • STK Push callback processing
  • C2B URL registration
  • C2B validation & confirmation handlers

Safaricom approved IP ranges for webhook origin validation:
  196.201.214.0/24, 196.201.216.0/23, 196.201.218.0/24
  196.201.214.0/24, 196.201.215.0/24

Phone normalisation: always convert to 2547XXXXXXXX format.
"""
from __future__ import annotations

import base64
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Safaricom IP ranges (document for future IP-filtering middleware) ──────────
# 196.201.214.0/24
# 196.201.215.0/24
# 196.201.216.0/23  (216 + 217)
# 196.201.218.0/24
SAFARICOM_IP_RANGES = [
    "196.201.214.",
    "196.201.215.",
    "196.201.216.",
    "196.201.217.",
    "196.201.218.",
]

# ── Token cache (per shortcode, process-level) ────────────────────────────────
# {shortcode: (token_str, expires_at)}
_token_cache: Dict[str, Tuple[str, datetime]] = {}

# ── API base URLs ─────────────────────────────────────────────────────────────
_BASE_URLS = {
    "sandbox":    "https://sandbox.safaricom.co.ke",
    "production": "https://api.safaricom.co.ke",
}


def _base_url(environment: str) -> str:
    return _BASE_URLS.get(environment, _BASE_URLS["sandbox"])


def normalize_phone(phone: str) -> str:
    """
    Convert any Kenyan phone format to 2547XXXXXXXX.
    Accepts: 07XXXXXXXX, +2547XXXXXXXX, 2547XXXXXXXX, 7XXXXXXXX
    """
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        phone = phone[1:]
    if phone.startswith("0"):
        phone = "254" + phone[1:]
    if phone.startswith("7") or phone.startswith("1"):
        phone = "254" + phone
    return phone


def _format_timestamp(dt: Optional[datetime] = None) -> str:
    """Safaricom timestamp format: YYYYMMDDHHmmss"""
    dt = dt or datetime.utcnow()
    return dt.strftime("%Y%m%d%H%M%S")


def _generate_password(shortcode: str, passkey: str, timestamp: str) -> str:
    """STK push password = base64(shortcode + passkey + timestamp)"""
    raw = f"{shortcode}{passkey}{timestamp}"
    return base64.b64encode(raw.encode()).decode()


# ── OAuth Token ────────────────────────────────────────────────────────────────

def get_access_token(consumer_key: str, consumer_secret: str, environment: str) -> str:
    """
    Fetch an OAuth2 access token from Safaricom.
    Token is cached per (consumer_key) for its TTL (usually 3600s).
    Returns the bearer token string.
    """
    cache_key = consumer_key[:16]  # use first 16 chars as cache key
    now = datetime.utcnow()

    if cache_key in _token_cache:
        token, expires_at = _token_cache[cache_key]
        if now < expires_at - timedelta(seconds=60):  # 60s buffer
            return token

    url = f"{_base_url(environment)}/oauth/v1/generate?grant_type=client_credentials"
    credentials = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()

    try:
        with httpx.Client(timeout=15) as client:
            response = client.get(url, headers={"Authorization": f"Basic {credentials}"})
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        logger.error(f"[mpesa] OAuth token request failed: {exc}")
        raise RuntimeError(f"Failed to get Mpesa access token: {exc}") from exc

    token = data.get("access_token")
    expires_in = int(data.get("expires_in", 3600))
    _token_cache[cache_key] = (token, now + timedelta(seconds=expires_in))

    logger.info(f"[mpesa] New access token obtained (expires in {expires_in}s)")
    return token


# ── STK Push ──────────────────────────────────────────────────────────────────

def initiate_stk_push(
    phone: str,
    amount: int,
    account_ref: str,
    description: str,
    shortcode: str,
    passkey: str,
    consumer_key: str,
    consumer_secret: str,
    environment: str,
    callback_url: str,
) -> Dict[str, Any]:
    """
    Trigger a Lipa Na Mpesa Online (STK Push) prompt on the tenant's phone.
    Returns the raw Safaricom response dict.
    """
    phone = normalize_phone(phone)
    timestamp = _format_timestamp()
    password = _generate_password(shortcode, passkey, timestamp)
    token = get_access_token(consumer_key, consumer_secret, environment)

    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(amount),
        "PartyA": phone,
        "PartyB": shortcode,
        "PhoneNumber": phone,
        "CallBackURL": callback_url,
        "AccountReference": account_ref[:12],  # Safaricom limit
        "TransactionDesc": description[:13],    # Safaricom limit
    }

    url = f"{_base_url(environment)}/mpesa/stkpush/v1/processrequest"
    logger.info(f"[mpesa] Initiating STK push to {phone} for KES {amount}")

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            result = response.json()
    except httpx.HTTPError as exc:
        logger.error(f"[mpesa] STK push HTTP error: {exc}")
        raise RuntimeError(f"STK Push request failed: {exc}") from exc

    if result.get("ResponseCode") != "0":
        logger.warning(f"[mpesa] STK push rejected: {result}")
    else:
        logger.info(f"[mpesa] STK push accepted: CheckoutRequestID={result.get('CheckoutRequestID')}")

    return result


def handle_stk_callback(payload: Dict[str, Any], owner_id: uuid.UUID, db) -> Optional[str]:
    """
    Process the Daraja STK callback.
    Creates a MpesaTransaction row on success, returns mpesa_receipt_number or None.
    Reconciliation is triggered via BackgroundTask (caller's responsibility).
    """
    from app.models.mpesa import MpesaTransaction, TransactionType, ReconciliationStatus

    try:
        body = payload.get("Body", {})
        stk_callback = body.get("stkCallback", {})
        result_code = stk_callback.get("ResultCode")

        if result_code != 0:
            logger.info(f"[mpesa] STK callback non-zero result: {result_code} — {stk_callback.get('ResultDesc')}")
            return None

        metadata = stk_callback.get("CallbackMetadata", {}).get("Item", [])
        meta = {item["Name"]: item.get("Value") for item in metadata}

        receipt = str(meta.get("MpesaReceiptNumber", ""))
        amount = float(meta.get("Amount", 0))
        phone = normalize_phone(str(meta.get("PhoneNumber", "")))
        txn_date_str = str(meta.get("TransactionDate", ""))

        try:
            txn_date = datetime.strptime(txn_date_str, "%Y%m%d%H%M%S")
        except (ValueError, TypeError):
            txn_date = datetime.utcnow()

        if not receipt:
            logger.warning("[mpesa] STK callback missing MpesaReceiptNumber")
            return None

        # Idempotency — skip if already stored
        existing = db.query(MpesaTransaction).filter(
            MpesaTransaction.mpesa_receipt_number == receipt
        ).first()
        if existing:
            logger.info(f"[mpesa] STK receipt {receipt} already stored (idempotent)")
            return receipt

        txn = MpesaTransaction(
            owner_id=owner_id,
            mpesa_receipt_number=receipt,
            transaction_type=TransactionType.STK_PUSH,
            phone_number=phone,
            amount=amount,
            account_reference=stk_callback.get("CheckoutRequestID", ""),
            transaction_desc="STK Push",
            transaction_date=txn_date,
            reconciliation_status=ReconciliationStatus.UNMATCHED,
            raw_payload=json.dumps(payload),
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)

        logger.info(f"[mpesa] Stored STK transaction {receipt} for owner {owner_id}")
        return receipt

    except Exception as exc:
        logger.error(f"[mpesa] handle_stk_callback error: {exc}", exc_info=True)
        db.rollback()
        return None


# ── C2B ───────────────────────────────────────────────────────────────────────

def register_c2b_urls(
    shortcode: str,
    consumer_key: str,
    consumer_secret: str,
    environment: str,
    confirmation_url: str,
    validation_url: str,
) -> Dict[str, Any]:
    """
    Register C2B confirmation and validation URLs with Safaricom.
    Must be called once when owner sets up (or changes) their shortcode.
    """
    token = get_access_token(consumer_key, consumer_secret, environment)
    url = f"{_base_url(environment)}/mpesa/c2b/v1/registerurl"

    payload = {
        "ShortCode": shortcode,
        "ResponseType": "Completed",  # or "Cancelled"
        "ConfirmationURL": confirmation_url,
        "ValidationURL": validation_url,
    }

    logger.info(f"[mpesa] Registering C2B URLs for shortcode {shortcode}")

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            result = response.json()
    except httpx.HTTPError as exc:
        logger.error(f"[mpesa] C2B URL registration HTTP error: {exc}")
        raise RuntimeError(f"C2B URL registration failed: {exc}") from exc

    logger.info(f"[mpesa] C2B URL registration response: {result}")
    return result


def handle_c2b_validation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate an incoming C2B payment.
    Returns {"ResultCode": 0, "ResultDesc": "Accepted"} to accept
    or {"ResultCode": 1, "ResultDesc": "Rejected"} to reject.
    Currently we accept all payments (validation is best-effort).
    """
    trans_id = payload.get("TransID", "")
    amount = payload.get("TransAmount", "0")
    phone = payload.get("MSISDN", "")
    bill_ref = payload.get("BillRefNumber", "")

    logger.info(f"[mpesa] C2B validation: {trans_id} | {phone} | KES {amount} | ref={bill_ref}")
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


def handle_c2b_confirmation(
    payload: Dict[str, Any],
    owner_id: uuid.UUID,
    db,
) -> Optional[str]:
    """
    Process a confirmed C2B payment. Stores transaction, triggers reconciliation.
    Returns mpesa_receipt_number or None on error.
    """
    from app.models.mpesa import MpesaTransaction, TransactionType, ReconciliationStatus

    try:
        receipt = str(payload.get("TransID", ""))
        if not receipt:
            logger.warning("[mpesa] C2B confirmation missing TransID")
            return None

        amount_str = payload.get("TransAmount", "0")
        try:
            amount = float(amount_str)
        except (ValueError, TypeError):
            amount = 0.0

        phone = normalize_phone(str(payload.get("MSISDN", "")))
        bill_ref = payload.get("BillRefNumber", "")
        trans_time_str = str(payload.get("TransTime", ""))

        try:
            txn_date = datetime.strptime(trans_time_str, "%Y%m%d%H%M%S")
        except (ValueError, TypeError):
            txn_date = datetime.utcnow()

        # Idempotency
        existing = db.query(MpesaTransaction).filter(
            MpesaTransaction.mpesa_receipt_number == receipt
        ).first()
        if existing:
            logger.info(f"[mpesa] C2B receipt {receipt} already stored (idempotent)")
            return receipt

        txn_type = TransactionType.PAYBILL  # Default; could be TILL based on shortcode type
        desc = " ".join(filter(None, [
            payload.get("FirstName", ""),
            payload.get("MiddleName", ""),
            payload.get("LastName", ""),
        ])).strip() or "C2B Payment"

        txn = MpesaTransaction(
            owner_id=owner_id,
            mpesa_receipt_number=receipt,
            transaction_type=txn_type,
            phone_number=phone,
            amount=amount,
            account_reference=bill_ref,
            transaction_desc=desc,
            transaction_date=txn_date,
            reconciliation_status=ReconciliationStatus.UNMATCHED,
            raw_payload=json.dumps(payload),
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)

        logger.info(f"[mpesa] Stored C2B transaction {receipt} KES {amount} from {phone}")
        return receipt

    except Exception as exc:
        logger.error(f"[mpesa] handle_c2b_confirmation error: {exc}", exc_info=True)
        db.rollback()
        return None


# ── CSV Import ────────────────────────────────────────────────────────────────

def parse_mpesa_csv(content: str) -> list[Dict[str, Any]]:
    """
    Parse Mpesa Business Statement CSV export.

    Column format (Safaricom standard):
      Receipt No | Completion Time | Details | Transaction Amount |
      Other Party Info | Balance | Reason Type | ...

    Returns a list of dicts with normalised field names.
    """
    import csv
    import io

    reader = csv.DictReader(io.StringIO(content))
    rows = []

    for row in reader:
        # Strip whitespace from keys
        row = {k.strip(): v.strip() for k, v in row.items() if k}

        receipt = row.get("Receipt No") or row.get("receipt_no") or row.get("TransID", "")
        completion_time = row.get("Completion Time") or row.get("completion_time", "")
        details = row.get("Details") or row.get("details", "")
        amount_str = row.get("Transaction Amount") or row.get("amount", "0")
        other_party = row.get("Other Party Info") or row.get("other_party_info", "")

        if not receipt:
            continue

        # Parse amount (may have commas)
        try:
            amount = float(str(amount_str).replace(",", ""))
        except (ValueError, TypeError):
            amount = 0.0

        # Parse date
        txn_date = None
        for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
            try:
                txn_date = datetime.strptime(completion_time, fmt)
                break
            except (ValueError, TypeError):
                continue
        if not txn_date:
            txn_date = datetime.utcnow()

        # Extract phone from other_party_info (typically "0712345678 - Name")
        phone = ""
        if other_party:
            parts = other_party.split(" - ")
            phone = normalize_phone(parts[0].strip()) if parts else ""

        rows.append({
            "receipt": receipt.strip(),
            "txn_date": txn_date,
            "details": details,
            "amount": amount,
            "phone": phone,
            "raw": row,
        })

    return rows
