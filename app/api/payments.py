"""
FastAPI Payment Routes
Handles payment initialization, verification, and subscription management
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import Optional
import uuid
from datetime import datetime, timedelta

from app.database import get_db
from app.models.payment import Payment, Subscription, PaymentStatus, PaymentGateway, PaymentMethod, SubscriptionStatus
from app.services.payment_gateways import PaystackService, FlutterwaveService
from app.services.currency_detector import currency_detector, CurrencyExchange
from app.schemas.payment import (
    InitiatePaymentRequest,
    InitiatePaymentResponse,
    VerifyPaymentRequest,
    SubscriptionRequest,
)
from app.config import settings
from app.core.security import get_current_user

router = APIRouter(prefix="/api/payments", tags=["payments"])

# Initialize gateway services
paystack_service = PaystackService(settings.PAYSTACK_SECRET_KEY)
flutterwave_service = FlutterwaveService(settings.FLUTTERWAVE_SECRET_KEY)


@router.post("/detect-gateway", response_model=dict)
async def detect_gateway(
    request: Request,
    country_code: Optional[str] = None,
    phone_number: Optional[str] = None
):
    """
    Auto-detect best payment gateway for user
    
    Returns recommended gateway, currency, and payment method
    """
    try:
        # Get client IP
        client_ip = request.client.host if request.client else "127.0.0.1"
        
        # Try detection in order of preference
        if country_code:
            result = currency_detector.detect_from_country_code(country_code)
        elif phone_number:
            result = currency_detector.detect_from_phone(phone_number)
        else:
            result = await currency_detector.detect_from_ip(client_ip)
        
        return {
            "success": True,
            "data": result,
            "available_methods": currency_detector.get_available_methods(result["country_code"])
        }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/initiate", response_model=InitiatePaymentResponse)
async def initiate_payment(
    payload: InitiatePaymentRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Initiate a payment transaction
    
    Automatically detects gateway and currency based on user location
    """
    try:
        # Generate unique reference
        reference = f"propertech_{uuid.uuid4().hex[:12]}"
        
        # Detect gateway if not specified
        if not payload.gateway:
            detection = await currency_detector.detect_from_ip("0.0.0.0")  # Would be client IP in real scenario
            gateway = detection["gateway"]
            currency = detection["currency"]
            method = detection["method"]
        else:
            gateway = payload.gateway
            currency = payload.currency or "KES"
            method = payload.method or "mpesa"
        
        # Create payment record
        payment = Payment(
            id=uuid.uuid4(),
            user_id=current_user.id,
            user_email=current_user.email,
            user_phone=current_user.phone,
            amount=payload.amount,
            currency=currency,
            gateway=gateway,
            method=method,
            reference=reference,
            plan_id=payload.plan_id,
            user_country=payload.country_code,
            user_ip=payload.ip_address,
            description=payload.description,
            status=PaymentStatus.PENDING
        )
        
        db.add(payment)
        db.commit()
        
        # Initialize payment with appropriate gateway
        if gateway == PaymentGateway.PAYSTACK:
            # Convert to kobo (smallest unit)
            amount_in_kobo = int(payload.amount * 100)
            
            response = await paystack_service.initialize_payment(
                amount=amount_in_kobo,
                email=current_user.email,
                reference=reference,
                callback_url=f"{settings.FRONTEND_URL}/payment/callback",
                metadata={
                    "user_id": str(current_user.id),
                    "plan_id": payload.plan_id,
                    "method": method
                }
            )
            
            if response.get("status"):
                return InitiatePaymentResponse(
                    success=True,
                    payment_id=str(payment.id),
                    reference=reference,
                    gateway="paystack",
                    authorization_url=response.get("data", {}).get("authorization_url"),
                    access_code=response.get("data", {}).get("access_code"),
                    amount=payload.amount,
                    currency=currency
                )
        
        elif gateway == PaymentGateway.FLUTTERWAVE:
            response = await flutterwave_service.initialize_payment(
                amount=payload.amount,
                currency=currency,
                email=current_user.email,
                phone_number=current_user.phone or "0000000000",
                tx_ref=reference,
                redirect_url=f"{settings.FRONTEND_URL}/payment/callback",
                first_name=current_user.first_name,
                last_name=current_user.last_name,
                metadata={"plan_id": payload.plan_id}
            )
            
            if response.get("status") == "success":
                payment_link = response.get("data", {}).get("link")
                return InitiatePaymentResponse(
                    success=True,
                    payment_id=str(payment.id),
                    reference=reference,
                    gateway="flutterwave",
                    authorization_url=payment_link,
                    amount=payload.amount,
                    currency=currency
                )
        
        raise HTTPException(status_code=400, detail="Payment initialization failed")
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/verify")
async def verify_payment(
    payload: VerifyPaymentRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Verify a completed payment
    """
    try:
        payment = db.query(Payment).filter(Payment.reference == payload.reference).first()
        
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        
        if payment.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Unauthorized")
        
        # Verify with appropriate gateway
        if payment.gateway == PaymentGateway.PAYSTACK:
            result = await paystack_service.verify_payment(payload.reference)
            
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
        
        elif payment.gateway == PaymentGateway.FLUTTERWAVE:
            # In real implementation, Flutterwave sends webhook
            # This is for manual verification
            transaction_id = payload.gateway_transaction_id
            result = await flutterwave_service.verify_payment(transaction_id)
            
            if result.get("status") == "success" and result.get("data", {}).get("status") == "successful":
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
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/subscribe")
async def create_subscription(
    payload: SubscriptionRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Create a subscription
    """
    try:
        # Detect gateway based on user location
        if not payload.gateway:
            detection = await currency_detector.detect_from_ip("0.0.0.0")
            gateway = detection["gateway"]
            currency = detection["currency"]
        else:
            gateway = payload.gateway
            currency = payload.currency or "KES"
        
        # Calculate amount based on plan and billing cycle
        plan_amounts = {
            "starter": {"monthly": 2900, "yearly": 29000},
            "professional": {"monthly": 9900, "yearly": 99000},
            "enterprise": {"monthly": 29900, "yearly": 299000}
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
            currency=currency,
            billing_cycle=payload.billing_cycle,
            amount=amount / 100,  # Convert to standard units
            gateway=gateway,
            start_date=datetime.utcnow(),
            next_billing_date=datetime.utcnow() + timedelta(days=30 if payload.billing_cycle == "monthly" else 365)
        )
        
        db.add(subscription)
        db.commit()
        
        # Initiate payment for subscription
        reference = f"sub_{uuid.uuid4().hex[:12]}"
        
        if gateway == PaymentGateway.PAYSTACK:
            amount_in_kobo = int(amount)
            
            response = await paystack_service.initialize_payment(
                amount=amount_in_kobo,
                email=current_user.email,
                reference=reference,
                callback_url=f"{settings.FRONTEND_URL}/subscription/callback",
                metadata={
                    "subscription_id": str(subscription.id),
                    "plan": payload.plan,
                    "billing_cycle": payload.billing_cycle
                }
            )
            
            return {
                "success": True,
                "subscription_id": str(subscription.id),
                "reference": reference,
                "gateway": "paystack",
                "authorization_url": response.get("data", {}).get("authorization_url")
            }
        
        elif gateway == PaymentGateway.FLUTTERWAVE:
            response = await flutterwave_service.initialize_payment(
                amount=amount / 100,
                currency=currency,
                email=current_user.email,
                phone_number=current_user.phone or "0000000000",
                tx_ref=reference,
                redirect_url=f"{settings.FRONTEND_URL}/subscription/callback",
                metadata={"subscription_id": str(subscription.id)}
            )
            
            return {
                "success": True,
                "subscription_id": str(subscription.id),
                "reference": reference,
                "gateway": "flutterwave",
                "authorization_url": response.get("data", {}).get("link")
            }
    
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
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))