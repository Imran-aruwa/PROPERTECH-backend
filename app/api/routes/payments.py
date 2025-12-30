"""
FastAPI Payment Routes - Paystack Only
Simplified payment handling
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import Optional
import uuid
import httpx
from datetime import datetime, timedelta

from app.database import get_db
from app.models.payment import Payment, Subscription, PaymentStatus, SubscriptionStatus
from app.schemas.payment import (
    InitiatePaymentRequest,
    InitiatePaymentResponse,
    VerifyPaymentRequest,
    SubscriptionRequest,
)
from app.core.config import settings
from app.core.security import get_current_user

router = APIRouter(tags=["payments"])

PAYSTACK_BASE_URL = "https://api.paystack.co"
PAYSTACK_SECRET_KEY = settings.PAYSTACK_SECRET_KEY


@router.post("/initiate", response_model=InitiatePaymentResponse)
async def initiate_payment(
    payload: InitiatePaymentRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Initiate a payment transaction with Paystack
    """
    try:
        # Generate unique reference
        reference = f"propertech_{uuid.uuid4().hex[:12]}"
        
        # Set currency and amount
        currency = payload.currency or "KES"
        amount_in_kobo = int(payload.amount * 100)
        
        # Create payment record
        payment = Payment(
            id=uuid.uuid4(),
            user_id=current_user.id,
            user_email=current_user.email,
            user_phone=current_user.phone,
            amount=payload.amount,
            currency=currency,
            gateway="paystack",
            method=payload.method or "card",
            reference=reference,
            plan_id=payload.plan_id,
            user_country=payload.country_code,
            user_ip=payload.ip_address,
            description=payload.description or f"Payment for {payload.plan_id}",
            status=PaymentStatus.PENDING
        )
        
        db.add(payment)
        db.commit()
        db.refresh(payment)
        
        # Initialize payment with Paystack
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{PAYSTACK_BASE_URL}/transaction/initialize",
                json={
                    "email": current_user.email,
                    "amount": amount_in_kobo,
                    "currency": currency,
                    "reference": reference,
                    "callback_url": f"{settings.FRONTEND_URL}/payment/callback",
                    "metadata": {
                        "user_id": str(current_user.id),
                        "plan_id": payload.plan_id,
                        "payment_id": str(payment.id),
                    }
                },
                headers={
                    "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail="Failed to initialize payment with Paystack"
                )
            
            paystack_response = response.json()
            
            if not paystack_response.get("status"):
                raise HTTPException(
                    status_code=400,
                    detail=paystack_response.get("message", "Paystack error")
                )
            
            data = paystack_response.get("data", {})
            
            return InitiatePaymentResponse(
                success=True,
                payment_id=str(payment.id),
                reference=reference,
                gateway="paystack",
                authorization_url=data.get("authorization_url"),
                access_code=data.get("access_code"),
                amount=payload.amount,
                currency=currency
            )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/verify")
async def verify_payment(
    payload: VerifyPaymentRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Verify a completed payment with Paystack
    """
    try:
        payment = db.query(Payment).filter(Payment.reference == payload.reference).first()
        
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        
        if payment.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Unauthorized")
        
        # Verify with Paystack
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{PAYSTACK_BASE_URL}/transaction/verify/{payload.reference}",
                headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Verification failed")
            
            result = response.json()
            
            if result.get("status") and result.get("data", {}).get("status") == "success":
                payment.status = PaymentStatus.COMPLETED
                payment.paid_at = datetime.utcnow()
                db.commit()
                
                return {
                    "success": True,
                    "status": "success",
                    "message": "Payment verified successfully",
                    "payment_id": str(payment.id)
                }
        
        raise HTTPException(status_code=400, detail="Payment verification failed")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/subscribe")
async def create_subscription(
    payload: SubscriptionRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Create a subscription and initiate payment
    """
    try:
        # Plan pricing in kobo (smallest unit)
        plan_amounts = {
            "starter": {"monthly": 290000, "yearly": 2900000},
            "professional": {"monthly": 990000, "yearly": 9900000},
            "enterprise": {"monthly": 299000, "yearly": 2990000}
        }
        
        if payload.plan not in plan_amounts:
            raise HTTPException(status_code=400, detail="Invalid plan")
        
        amount = plan_amounts[payload.plan][payload.billing_cycle]
        
        # Create subscription record
        subscription = Subscription(
            id=uuid.uuid4(),
            user_id=current_user.id,
            plan=payload.plan,
            status=SubscriptionStatus.PENDING,
            currency="KES",
            billing_cycle=payload.billing_cycle,
            amount=amount / 100,  # Convert back to KES
            gateway="paystack",
            start_date=datetime.utcnow(),
            next_billing_date=datetime.utcnow() + timedelta(days=30 if payload.billing_cycle == "monthly" else 365)
        )
        
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
        
        # Initiate payment for subscription
        reference = f"sub_{uuid.uuid4().hex[:12]}"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{PAYSTACK_BASE_URL}/transaction/initialize",
                json={
                    "email": current_user.email,
                    "amount": amount,
                    "currency": "KES",
                    "reference": reference,
                    "callback_url": f"{settings.FRONTEND_URL}/subscription/callback",
                    "metadata": {
                        "subscription_id": str(subscription.id),
                        "plan": payload.plan,
                        "billing_cycle": payload.billing_cycle
                    }
                },
                headers={
                    "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to initialize subscription")
            
            paystack_response = response.json()
            data = paystack_response.get("data", {})
            
            return {
                "success": True,
                "subscription_id": str(subscription.id),
                "reference": reference,
                "gateway": "paystack",
                "authorization_url": data.get("authorization_url"),
                "amount": amount / 100,
                "currency": "KES"
            }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/history")
async def payment_history(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
    skip: int = 0,
    limit: int = 10
):
    """
    Get user's payment history
    """
    payments = db.query(Payment)\
        .filter(Payment.user_id == current_user.id)\
        .order_by(Payment.created_at.desc())\
        .offset(skip)\
        .limit(limit)\
        .all()
    
    return {
        "success": True,
        "payments": [
            {
                "id": str(p.id),
                "amount": p.amount,
                "currency": p.currency,
                "gateway": p.gateway,
                "status": p.status,
                "created_at": p.created_at.isoformat()
            }
            for p in payments
        ]
    }


@router.get("/subscriptions")
async def get_subscriptions(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Get user's active subscriptions
    """
    subscriptions = db.query(Subscription)\
        .filter(Subscription.user_id == current_user.id)\
        .filter(Subscription.status == SubscriptionStatus.ACTIVE)\
        .all()
    
    return {
        "success": True,
        "subscriptions": [
            {
                "id": str(s.id),
                "plan": s.plan,
                "billing_cycle": s.billing_cycle,
                "amount": s.amount,
                "currency": s.currency,
                "status": s.status,
                "next_billing_date": s.next_billing_date.isoformat() if s.next_billing_date else None
            }
            for s in subscriptions
        ]
    }


@router.post("/cancel-subscription/{subscription_id}")
async def cancel_subscription(
    subscription_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Cancel a subscription
    """
    try:
        subscription = db.query(Subscription)\
            .filter(Subscription.id == subscription_id)\
            .filter(Subscription.user_id == current_user.id)\
            .first()

        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")

        subscription.status = SubscriptionStatus.CANCELLED
        subscription.cancelled_at = datetime.utcnow()
        db.commit()

        return {
            "success": True,
            "message": "Subscription cancelled successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhook")
async def paystack_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Paystack webhook endpoint for payment verification
    Handles: charge.success, transfer.success, subscription.create, etc.
    """
    import hashlib
    import hmac

    try:
        # Get the raw body
        body = await request.body()
        payload = await request.json()

        # Verify webhook signature (in production)
        signature = request.headers.get("x-paystack-signature", "")
        if PAYSTACK_SECRET_KEY and signature:
            expected_signature = hmac.new(
                PAYSTACK_SECRET_KEY.encode(),
                body,
                hashlib.sha512
            ).hexdigest()

            if signature != expected_signature:
                raise HTTPException(status_code=400, detail="Invalid signature")

        event = payload.get("event")
        data = payload.get("data", {})

        if event == "charge.success":
            # Payment was successful
            reference = data.get("reference")

            payment = db.query(Payment).filter(Payment.reference == reference).first()
            if payment:
                payment.status = PaymentStatus.COMPLETED
                payment.transaction_id = str(data.get("id", ""))
                payment.paid_at = datetime.utcnow()
                db.commit()

        elif event == "transfer.success":
            # Transfer was successful
            reference = data.get("reference")
            # Handle transfer success

        elif event == "subscription.create":
            # New subscription created
            pass

        elif event == "subscription.disable":
            # Subscription disabled/cancelled
            customer_code = data.get("customer", {}).get("customer_code")
            # Find and update subscription

        elif event == "charge.failed":
            # Payment failed
            reference = data.get("reference")

            payment = db.query(Payment).filter(Payment.reference == reference).first()
            if payment:
                payment.status = PaymentStatus.FAILED
                db.commit()

        return {"success": True, "message": "Webhook received"}

    except HTTPException:
        raise
    except Exception as e:
        # Log error but return 200 to prevent webhook retry
        import logging
        logging.error(f"Webhook error: {e}")
        return {"success": True, "message": "Webhook processed"}


@router.put("/{payment_id}")
async def update_payment(
    payment_id: str,
    payment_status: Optional[str] = None,
    transaction_id: Optional[str] = None,
    payment_method: Optional[str] = None,
    payment_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Update payment status (for admin/owner use)
    """
    from app.models.user import UserRole

    # Only allow owners and admins to update payments
    if current_user.role not in [UserRole.OWNER, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Access denied")

    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    if payment_status:
        status_map = {
            "pending": PaymentStatus.PENDING,
            "processing": PaymentStatus.PROCESSING,
            "completed": PaymentStatus.COMPLETED,
            "failed": PaymentStatus.FAILED,
            "cancelled": PaymentStatus.CANCELLED,
            "refunded": PaymentStatus.REFUNDED
        }
        payment.status = status_map.get(payment_status.lower(), payment.status)

    if transaction_id:
        payment.transaction_id = transaction_id

    if payment_method:
        payment.method = payment_method

    if payment_date:
        try:
            payment.payment_date = datetime.fromisoformat(payment_date)
        except:
            pass

    payment.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(payment)

    return {
        "success": True,
        "message": "Payment updated successfully",
        "payment_id": str(payment.id),
        "status": payment.status.value
    }