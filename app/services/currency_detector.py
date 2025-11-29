"""
Currency and Gateway Detection Service
Auto-detects best payment gateway for user based on location
"""

import httpx
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class CurrencyDetector:
    """Detect user location and recommend best payment gateway"""
    
    # Gateway configurations by country/region
    GATEWAY_MAPPING = {
        # East Africa - Paystack (M-Pesa support)
        "KE": {"gateway": "paystack", "currency": "KES", "method": "mpesa"},
        "UG": {"gateway": "paystack", "currency": "UGX", "method": "mpesa"},
        "TZ": {"gateway": "paystack", "currency": "TZS", "method": "mpesa"},
        "RW": {"gateway": "paystack", "currency": "RWF", "method": "mpesa"},
        
        # West Africa - Flutterwave
        "NG": {"gateway": "flutterwave", "currency": "NGN", "method": "card"},
        "GH": {"gateway": "flutterwave", "currency": "GHS", "method": "card"},
        "ZA": {"gateway": "flutterwave", "currency": "ZAR", "method": "card"},
        
        # Default for unknown countries
        "default": {"gateway": "flutterwave", "currency": "USD", "method": "usd_card"},
    }
    
    PAYMENT_METHODS = {
        "mpesa": "M-Pesa",
        "card": "Card",
        "kes_card": "KES Card",
        "usd_card": "USD Card",
        "apple_pay": "Apple Pay",
        "google_pay": "Google Pay",
    }
    
    @staticmethod
    async def detect_from_ip(client_ip: Optional[str] = None) -> Dict:
        """
        Detect user's country from IP and return gateway config
        
        Args:
            client_ip: Optional client IP address
            
        Returns:
            Dict with gateway, currency, method, country_code
        """
        try:
            country_code = await CurrencyDetector._get_country_from_ip(client_ip)
            config = CurrencyDetector.GATEWAY_MAPPING.get(
                country_code,
                CurrencyDetector.GATEWAY_MAPPING["default"]
            )
            
            return {
                "gateway": config["gateway"],
                "currency": config["currency"],
                "method": config["method"],
                "country_code": country_code,
            }
        except Exception as e:
            logger.error(f"Error detecting gateway: {str(e)}")
            # Return default config on error
            return {
                "gateway": "flutterwave",
                "currency": "USD",
                "method": "usd_card",
                "country_code": "DEFAULT",
            }
    
    @staticmethod
    async def _get_country_from_ip(client_ip: Optional[str] = None) -> str:
        """
        Get country code from IP using geolocation service
        
        Args:
            client_ip: Optional client IP address
            
        Returns:
            Country code (e.g., "KE", "NG")
        """
        try:
            # Use ip-api.com (free tier, 45 req/min)
            url = "http://ip-api.com/json/"
            params = {"fields": "countryCode", "lang": "en"}
            
            if client_ip and client_ip != "127.0.0.1":
                params["query"] = client_ip
            
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url, params=params)
                data = response.json()
                
                if data.get("status") == "success":
                    country_code = data.get("countryCode", "DEFAULT").upper()
                    logger.info(f"Detected country: {country_code}")
                    return country_code
                    
        except Exception as e:
            logger.warning(f"IP geolocation failed: {str(e)}")
        
        # Default to Kenya if detection fails
        return "KE"
    
    @staticmethod
    def get_gateway_for_country(country_code: str) -> Dict:
        """
        Get gateway configuration for a specific country
        
        Args:
            country_code: ISO country code (e.g., "KE", "NG")
            
        Returns:
            Gateway configuration dict
        """
        config = CurrencyDetector.GATEWAY_MAPPING.get(
            country_code.upper(),
            CurrencyDetector.GATEWAY_MAPPING["default"]
        )
        
        return {
            "gateway": config["gateway"],
            "currency": config["currency"],
            "method": config["method"],
            "country_code": country_code.upper(),
        }
    
    @staticmethod
    def get_payment_method_name(method: str) -> str:
        """Get display name for payment method"""
        return CurrencyDetector.PAYMENT_METHODS.get(method, method)
    
    @staticmethod
    def validate_currency(currency: str) -> bool:
        """Validate if currency is supported"""
        supported = {"KES", "UGX", "TZS", "RWF", "NGN", "GHS", "ZAR", "USD"}
        return currency.upper() in supported


# Singleton instance
currency_detector = CurrencyDetector()