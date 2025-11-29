"""
Daraja API Service (Safaricom M-Pesa)
Handles M-Pesa payments for Kenya
"""
import httpx
import logging
import base64
from typing import Dict, Optional, Any
from datetime import datetime
from app.config import settings

logger = logging.getLogger(__name__)


class DarajaService:
    """Safaricom Daraja API integration for M-Pesa"""
    
    def __init__(
        self,
        consumer_key: str = settings.DARAJA_CONSUMER_KEY,
        consumer_secret: str = settings.DARAJA_CONSUMER_SECRET,
        business_shortcode: str = settings.DARAJA_BUSINESS_SHORTCODE,
        passkey: str = settings.DARAJA_PASSKEY
    ):
        """
        Initialize Daraja service
        
        Args:
            consumer_key: Daraja consumer key
            consumer_secret: Daraja consumer secret
            business_shortcode: M-Pesa business shortcode
            passkey: M-Pesa passkey
        """
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.business_shortcode = business_shortcode
        self.passkey = passkey
        self.base_url = "https://api.safaricom.co.ke"
        self.auth_url = f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials"
        self.access_token = None
    
    async def get_access_token(self) -> str:
        """
        Get OAuth access token from Daraja API
        
        Returns:
            Access token string
        """
        try:
            # Create basic auth header
            auth_string = f"{self.consumer_key}:{self.consumer_secret}"
            auth_bytes = auth_string.encode("utf-8")
            auth_base64 = base64.b64encode(auth_bytes).decode("utf-8")
            
            headers = {
                "Authorization": f"Basic {auth_base64}"
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(self.auth_url, headers=headers, timeout=10.0)
                response.raise_for_status()
                data = response.json()
                self.access_token = data.get("access_token")
                return self.access_token
                
        except Exception as e:
            logger.error(f"Failed to get Daraja access token: {e}")
            raise Exception(f"Authentication failed: {str(e)}")
    
    async def initiate_payment(
        self,
        phone_number: str,
        amount: int,
        reference: str,
        description: str = "PROPERTECH Payment",
        callback_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Initiate M-Pesa payment (STK Push)
        
        Args:
            phone_number: Customer phone in format 254XXXXXXXXX
            amount: Amount in KES
            reference: Unique reference/order ID
            description: Payment description
            callback_url: Callback URL for payment result
            
        Returns:
            Response with checkout request ID and response code
        """
        try:
            # Get access token
            if not self.access_token:
                await self.get_access_token()
            
            # Format phone number
            if phone_number.startswith("0"):
                phone_number = "254" + phone_number[1:]
            elif not phone_number.startswith("254"):
                phone_number = "254" + phone_number
            
            # Generate timestamp
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            
            # Generate password
            password_string = f"{self.business_shortcode}{self.passkey}{timestamp}"
            password_bytes = password_string.encode("utf-8")
            password_base64 = base64.b64encode(password_bytes).decode("utf-8")
            
            # Prepare payload
            payload = {
                "BusinessShortCode": self.business_shortcode,
                "Password": password_base64,
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": amount,
                "PartyA": phone_number,
                "PartyB": self.business_shortcode,
                "PhoneNumber": phone_number,
                "CallBackURL": callback_url or f"{settings.BACKEND_URL}/api/v1/webhooks/daraja",
                "AccountReference": reference,
                "TransactionDesc": description
            }
            
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            url = f"{self.base_url}/mpesa/stkpush/v1/processrequest"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
                
                if data.get("ResponseCode") == "0":
                    return {
                        "success": True,
                        "checkout_request_id": data.get("CheckoutRequestID"),
                        "response_code": data.get("ResponseCode"),
                        "response_description": data.get("ResponseDescription"),
                        "customer_message": data.get("CustomerMessage"),
                        "reference": reference
                    }
                else:
                    return {
                        "success": False,
                        "error": data.get("ResponseDescription"),
                        "response_code": data.get("ResponseCode")
                    }
                    
        except Exception as e:
            logger.error(f"Daraja payment initiation error: {e}")
            return {"success": False, "error": str(e)}
    
    async def query_payment_status(self, checkout_request_id: str) -> Dict[str, Any]:
        """
        Query payment status using checkout request ID
        
        Args:
            checkout_request_id: Checkout request ID from initiate_payment
            
        Returns:
            Payment status and details
        """
        try:
            # Get access token
            if not self.access_token:
                await self.get_access_token()
            
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            
            # Generate password
            password_string = f"{self.business_shortcode}{self.passkey}{timestamp}"
            password_bytes = password_string.encode("utf-8")
            password_base64 = base64.b64encode(password_bytes).decode("utf-8")
            
            payload = {
                "BusinessShortCode": self.business_shortcode,
                "Password": password_base64,
                "Timestamp": timestamp,
                "CheckoutRequestID": checkout_request_id
            }
            
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            url = f"{self.base_url}/mpesa/stkpushquery/v1/query"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
                
                return {
                    "success": True,
                    "response_code": data.get("ResponseCode"),
                    "response_description": data.get("ResponseDescription"),
                    "result_code": data.get("ResultCode"),
                    "result_description": data.get("ResultDesc"),
                    "checkout_request_id": checkout_request_id
                }
                
        except Exception as e:
            logger.error(f"Daraja query error: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
daraja_service = DarajaService()