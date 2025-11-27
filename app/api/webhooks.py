"""
Webhook Handlers for Payment Gateways
Processes Paystack and Flutterwave webhook events
"""
import json
import hmac
import hashlib
import logging
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.database import get_db
from app.models.payment import (
    Payment, Subscription, PaymentStatus, SubscriptionStatus, PaymentGatewayLog
)
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


class WebhookValidator:
    """Validate webhook signatures from payment gateways"""
    
    @staticmethod
    def validate_paystack_signature(
        signature: str,
        body: bytes,
        secret_key: str
    ) -> bool:
        """
        Validate Paystack webhook signature
        
        Args:
            signature: x-paystack-signature header value
            body: Request body bytes
            secret_key: Paystack secret key
            
        Returns:
            True if valid, False otherwise
        """
        try:
            hash_object = hmac.new(
                secret_key.encode(),
                body,
                hashlib.sha512
            )
            computed_signature = hash_object.hexdigest()
            return computed_signature == signature
        except Exception as e:
            logger.error(f"Paystack signature validation error: {e}")
            return False
    
    @staticmethod
    def validate_flutterwave_signature(
        signature: str,
        body: bytes,
        secret_hash: str
    ) -> bool:
        """
        Validate Flutterwave webhook signature
        
        Args:
            signature: verificationHash header value
            body: Request body bytes
            secret_hash: Flutterwave webhook secret hash
            
        Returns:
            True if valid, False otherwise
        """
        try:
            hash_object = hmac.new(
                secret_hash.encode(),
                body,
                hashlib.sha256
            )
            computed_signature = hash_object.hexdigest()
            return computed_signature == signature
        except Exception as e:
            logger.error(f"Flutterwave signature validation error: {e}")
            return False


@router.post("/paystack")
async def paystack_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_paystack_signature: str = None
):
    """
    Paystack webhook handler
    
    Processes payment confirmations from Paystack
    Webhook events: charge.success, charge.failed, subscription.create, subscription.disable
    """
    try:
        # Get raw body for signature validation
        body = await request.body()
        
        # Validate signature
        if not WebhookValidator.validate_paystack_signature(
            x_paystack_signature,
            body,
            settings.PAYSTACK_SECRET_KEY
        ):
            logger.warning("Invalid Paystack signature")
            raise HTTPException(status_code=401, detail="Invalid signature")
        
        # Parse payload
        payload = json.loads(body)
        
        event = payload.get("event")
        data = payload.get("data", {})
        
        logger.info(f"Paystack webhook event: {event}")
        
        # Handle charge.success event
        if event == "charge.success":
            reference = data.get("reference")
            status = data.get("status")
            customer_code = data.get("customer", {}).get("customer_code")
            authorization = data.get("authorization", {})
            auth_code = authorization.get("authorization_code")
            
            # Find payment
            payment = db.query(Payment).filter(Payment.reference == reference).first()
            
            if not payment:
                logger.warning(f"Payment not found for reference: {reference}")
                return {"success": False, "message": "Payment not found"}
            
            # Log webhook
            log = PaymentGatewayLog(
                payment_id=payment.id,
                gateway="paystack",
                action="charge.success",
                request_data=json.dumps(payload),
                response_data=json.dumps(data),
                status_code=200
            )
            db.add(log)
            
            # Update payment status
            if status == "success":
                payment.status = PaymentStatus.COMPLETED
                payment.paid_at = datetime.utcnow()
                payment.gateway_response = json.dumps(data)
                payment.transaction_id = str(data.get("id"))
                
                # If this is a subscription payment, update subscription
                if payment.subscription_id:
                    subscription = db.query(Subscription).filter(
                        Subscription.id == payment.subscription_id
                    ).first()
                    
                    if subscription:
                        subscription.status = SubscriptionStatus.ACTIVE
                        subscription.payment_count = (subscription.payment_count or 0) + 1
                        subscription.last_payment_date = datetime.utcnow()
                        subscription.gateway_customer_id = customer_code
                        subscription.gateway_subscription_id = auth_code
                        
                        # Set next billing date
                        if subscription.billing_cycle == "monthly":
                            subscription.next_billing_date = datetime.utcnow() + timedelta(days=30)
                        else:
                            subscription.next_billing_date = datetime.utcnow() + timedelta(days=365)
                
                logger.info(f"Payment {reference} completed successfully")
            else:
                payment.status = PaymentStatus.FAILED
                logger.warning(f"Payment {reference} failed with status: {status}")
            
            db.commit()
            return {"success": True, "message": "Webhook processed"}
        
        # Handle charge.failed event
        elif event == "charge.failed":
            reference = data.get("reference")
            
            payment = db.query(Payment).filter(Payment.reference == reference).first()
            if payment:
                payment.status = PaymentStatus.FAILED
                payment.gateway_response = json.dumps(data)
                db.commit()
                logger.info(f"Payment {reference} marked as failed")
            
            return {"success": True, "message": "Charge failed processed"}
        
        # Handle subscription.create event
        elif event == "subscription.create":
            logger.info("Subscription created")
            return {"success": True, "message": "Subscription created"}
        
        # Handle subscription.disable event
        elif event == "subscription.disable":
            customer_code = data.get("customer", {}).get("customer_code")
            subscriptions = db.query(Subscription).filter(
                Subscription.gateway_customer_id == customer_code
            ).all()
            
            for sub in subscriptions:
                sub.status = SubscriptionStatus.CANCELLED
                sub.cancelled_at = datetime.utcnow()
            
            db.commit()
            logger.info(f"Subscription disabled for customer: {customer_code}")
            return {"success": True, "message": "Subscription disabled"}
        
        return {"success": True, "message": "Event processed"}
    
    except Exception as e:
        logger.error(f"Paystack webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/flutterwave")
async def flutterwave_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Flutterwave webhook handler
    
    Processes payment confirmations from Flutterwave
    Webhook events: charge.complete, charge.failed
    """
    try:
        # Get raw body for signature validation
        body = await request.body()
        
        # Get verification hash from headers
        verificationhash = request.headers.get("verificationHash")
        
        # Validate signature
        if not WebhookValidator.validate_flutterwave_signature(
            verificationhash,
            body,
            settings.FLUTTERWAVE_WEBHOOK_HASH
        ):
            logger.warning("Invalid Flutterwave signature")
            raise HTTPException(status_code=401, detail="Invalid signature")
        
        # Parse payload
        payload = json.loads(body)
        
        event = payload.get("event")
        data = payload.get("data", {})
        
        logger.info(f"Flutterwave webhook event: {event}")
        
        # Handle successful charge
        if event == "charge.complete":
            status = data.get("status")
            tx_ref = data.get("tx_ref")
            flw_ref = data.get("flw_ref")
            transaction_id = data.get("id")
            amount = data.get("amount_settled")
            currency = data.get("currency")
            customer = data.get("customer", {})
            
            # Find payment by reference
            payment = db.query(Payment).filter(Payment.reference == tx_ref).first()
            
            if not payment:
                logger.warning(f"Payment not found for reference: {tx_ref}")
                return {"success": False, "message": "Payment not found"}
            
            # Log webhook
            log = PaymentGatewayLog(
                payment_id=payment.id,
                gateway="flutterwave",
                action="charge.complete",
                request_data=json.dumps(payload),
                response_data=json.dumps(data),
                status_code=200
            )
            db.add(log)
            
            # Update payment status
            if status == "successful":
                payment.status = PaymentStatus.COMPLETED
                payment.paid_at = datetime.utcnow()
                payment.transaction_id = str(transaction_id)
                payment.gateway_response = json.dumps(data)
                
                # If this is a subscription payment, update subscription
                if payment.subscription_id:
                    subscription = db.query(Subscription).filter(
                        Subscription.id == payment.subscription_id
                    ).first()
                    
                    if subscription:
                        subscription.status = SubscriptionStatus.ACTIVE
                        subscription.payment_count = (subscription.payment_count or 0) + 1
                        subscription.last_payment_date = datetime.utcnow()
                        subscription.gateway_subscription_id = flw_ref
                        
                        # Set next billing date
                        if subscription.billing_cycle == "monthly":
                            subscription.next_billing_date = datetime.utcnow() + timedelta(days=30)
                        else:
                            subscription.next_billing_date = datetime.utcnow() + timedelta(days=365)
                
                logger.info(f"Payment {tx_ref} completed successfully via Flutterwave")
            else:
                payment.status = PaymentStatus.FAILED
                logger.warning(f"Payment {tx_ref} failed with status: {status}")
            
            db.commit()
            return {"success": True, "message": "Webhook processed"}
        
        # Handle failed charge
        elif event == "charge.failed":
            tx_ref = data.get("tx_ref")
            
            payment = db.query(Payment).filter(Payment.reference == tx_ref).first()
            if payment:
                payment.status = PaymentStatus.FAILED
                payment.gateway_response = json.dumps(data)
                db.commit()
                logger.info(f"Payment {tx_ref} marked as failed")
            
            return {"success": True, "message": "Charge failed processed"}
        
        return {"success": True, "message": "Event processed"}
    
    except Exception as e:
        logger.error(f"Flutterwave webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def webhook_health():
    """Health check endpoint for webhooks"""
    return {
        "success": True,
        "message": "Webhook service is running",
        "timestamp": datetime.utcnow().isoformat()
    }