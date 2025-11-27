"""
Payment Gateway Integration Services
Handles Paystack and Flutterwave API interactions
"""
import httpx
import json
import logging
from typing import Dict, Optional, Any
from datetime import datetime
from app.config import settings
logger = logging.getLogger(__name__)


class PaystackService:
    """Paystack payment gateway integration"""
    
    def __init__(self, secret_key: str):
        """
        Initialize Paystack service
        
        Args:
            secret_key: Paystack secret key from dashboard
        """
        self.secret_key = secret_key
        self.base_url = "https://api.paystack.co"
        self.headers = {
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json"
        }
    
    async def initialize_payment(
        self,
        amount: int,  # Amount in kobo (1 KES = 100 kobo, 1 USD = 100 cents)
        email: str,
        reference: str,
        callback_url: str,
        metadata: Optional[Dict] = None,
        plan: Optional[str] = None,  # subscription plan ID
    ) -> Dict[str, Any]:
        """
        Initialize a transaction
        
        Args:
            amount: Amount in smallest unit (kobo for KES, cents for USD)
            email: Customer email
            reference: Unique transaction reference
            callback_url: URL to redirect after payment
            metadata: Additional data to attach
            plan: Plan ID for subscription
            
        Returns:
            API response with authorization_url, access_code, reference
        """
        payload = {
            "amount": amount,
            "email": email,
            "reference": reference,
            "callback_url": callback_url,
        }
        
        if metadata:
            payload["metadata"] = metadata
        
        if plan:
            payload["plan"] = plan
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/transaction/initialize",
                    json=payload,
                    headers=self.headers,
                    timeout=10.0
                )
                response.raise_for_status()
                return response.json()
        
        except httpx.HTTPError as e:
            logger.error(f"Paystack initialize error: {e}")
            raise Exception(f"Paystack initialization failed: {str(e)}")
    
    async def verify_payment(self, reference: str) -> Dict[str, Any]:
        """
        Verify a payment transaction
        
        Args:
            reference: Transaction reference
            
        Returns:
            Transaction details including status
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/transaction/verify/{reference}",
                    headers=self.headers,
                    timeout=10.0
                )
                response.raise_for_status()
                return response.json()
        
        except httpx.HTTPError as e:
            logger.error(f"Paystack verify error: {e}")
            raise Exception(f"Payment verification failed: {str(e)}")
    
    async def create_subscription_plan(
        self,
        name: str,
        amount: int,  # Amount in kobo
        interval: str,  # monthly, yearly
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a subscription plan
        
        Args:
            name: Plan name
            amount: Amount per interval
            interval: billing interval
            description: Plan description
            
        Returns:
            Plan details including plan_code
        """
        payload = {
            "name": name,
            "amount": amount,
            "interval": interval,
        }
        
        if description:
            payload["description"] = description
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/plan",
                    json=payload,
                    headers=self.headers,
                    timeout=10.0
                )
                response.raise_for_status()
                return response.json()
        
        except httpx.HTTPError as e:
            logger.error(f"Paystack plan creation error: {e}")
            raise Exception(f"Plan creation failed: {str(e)}")
    
    async def create_customer(
        self,
        email: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        phone: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a customer record
        
        Args:
            email: Customer email
            first_name: Customer first name
            last_name: Customer last name
            phone: Customer phone
            
        Returns:
            Customer details including customer_code
        """
        payload = {
            "email": email,
        }
        
        if first_name:
            payload["first_name"] = first_name
        if last_name:
            payload["last_name"] = last_name
        if phone:
            payload["phone"] = phone
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/customer",
                    json=payload,
                    headers=self.headers,
                    timeout=10.0
                )
                response.raise_for_status()
                return response.json()
        
        except httpx.HTTPError as e:
            logger.error(f"Paystack customer creation error: {e}")
            raise Exception(f"Customer creation failed: {str(e)}")
    
    async def create_subscription(
        self,
        customer_code: str,
        plan_code: str,
        authorization_code: str,
        start_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a subscription for a customer
        
        Args:
            customer_code: Customer code from create_customer
            plan_code: Plan code from create_subscription_plan
            authorization_code: Authorization code from previous payment
            start_date: Subscription start date (ISO format)
            
        Returns:
            Subscription details
        """
        payload = {
            "customer": customer_code,
            "plan": plan_code,
            "authorization": authorization_code,
        }
        
        if start_date:
            payload["start_date"] = start_date
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/subscription",
                    json=payload,
                    headers=self.headers,
                    timeout=10.0
                )
                response.raise_for_status()
                return response.json()
        
        except httpx.HTTPError as e:
            logger.error(f"Paystack subscription error: {e}")
            raise Exception(f"Subscription creation failed: {str(e)}")
    
    async def charge_authorization(
        self,
        authorization_code: str,
        amount: int,
        email: str,
        reference: str
    ) -> Dict[str, Any]:
        """
        Charge an authorization (for recurring payments)
        
        Args:
            authorization_code: Authorization code to charge
            amount: Amount in kobo
            email: Customer email
            reference: Transaction reference
            
        Returns:
            Charge result
        """
        payload = {
            "authorization_code": authorization_code,
            "amount": amount,
            "email": email,
            "reference": reference,
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/transaction/charge_authorization",
                    json=payload,
                    headers=self.headers,
                    timeout=10.0
                )
                response.raise_for_status()
                return response.json()
        
        except httpx.HTTPError as e:
            logger.error(f"Paystack charge authorization error: {e}")
            raise Exception(f"Charge failed: {str(e)}")


class FlutterwaveService:
    """Flutterwave payment gateway integration"""
    
    def __init__(self, secret_key: str):
        """
        Initialize Flutterwave service
        
        Args:
            secret_key: Flutterwave secret key from dashboard
        """
        self.secret_key = secret_key
        self.base_url = "https://api.flutterwave.com/v3"
        self.headers = {
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json"
        }
    
    async def initialize_payment(
        self,
        amount: float,
        currency: str,
        email: str,
        phone_number: str,
        tx_ref: str,
        redirect_url: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Initialize a payment
        
        Args:
            amount: Amount to charge
            currency: Currency code (USD, KES, etc.)
            email: Customer email
            phone_number: Customer phone
            tx_ref: Unique transaction reference
            redirect_url: Redirect URL after payment
            first_name: Customer first name
            last_name: Customer last name
            metadata: Additional metadata
            
        Returns:
            API response with payment link
        """
        payload = {
            "tx_ref": tx_ref,
            "amount": amount,
            "currency": currency,
            "redirect_url": redirect_url,
            "customer": {
                "email": email,
                "phonenumber": phone_number,
            }
        }
        
        if first_name:
            payload["customer"]["name"] = f"{first_name} {last_name or ''}".strip()
        
        if metadata:
            payload["meta"] = metadata
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/payments",
                    json=payload,
                    headers=self.headers,
                    timeout=10.0
                )
                response.raise_for_status()
                return response.json()
        
        except httpx.HTTPError as e:
            logger.error(f"Flutterwave initialize error: {e}")
            raise Exception(f"Flutterwave initialization failed: {str(e)}")
    
    async def verify_payment(self, transaction_id: str) -> Dict[str, Any]:
        """
        Verify a payment
        
        Args:
            transaction_id: Flutterwave transaction ID
            
        Returns:
            Transaction details
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/transactions/{transaction_id}/verify",
                    headers=self.headers,
                    timeout=10.0
                )
                response.raise_for_status()
                return response.json()
        
        except httpx.HTTPError as e:
            logger.error(f"Flutterwave verify error: {e}")
            raise Exception(f"Payment verification failed: {str(e)}")
    
    async def create_payment_plan(
        self,
        name: str,
        amount: float,
        interval: str,
        duration: int,
        currency: str = "USD"
    ) -> Dict[str, Any]:
        """
        Create a payment plan for subscriptions
        
        Args:
            name: Plan name
            amount: Amount per interval
            interval: Billing interval (monthly, yearly, etc.)
            duration: Number of intervals
            currency: Currency code
            
        Returns:
            Plan details including plan_id
        """
        payload = {
            "amount": amount,
            "name": name,
            "interval": interval,
            "duration": duration,
            "currency": currency,
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/payment-plans",
                    json=payload,
                    headers=self.headers,
                    timeout=10.0
                )
                response.raise_for_status()
                return response.json()
        
        except httpx.HTTPError as e:
            logger.error(f"Flutterwave plan creation error: {e}")
            raise Exception(f"Plan creation failed: {str(e)}")
    
    async def refund_payment(
        self,
        transaction_id: str,
        amount: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Refund a payment
        
        Args:
            transaction_id: Transaction ID to refund
            amount: Amount to refund (None for full refund)
            
        Returns:
            Refund result
        """
        payload = {}
        
        if amount:
            payload["amount"] = amount
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/transactions/{transaction_id}/refund",
                    json=payload,
                    headers=self.headers,
                    timeout=10.0
                )
                response.raise_for_status()
                return response.json()
        
        except httpx.HTTPError as e:
            logger.error(f"Flutterwave refund error: {e}")
            raise Exception(f"Refund failed: {str(e)}")