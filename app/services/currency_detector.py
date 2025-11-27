"""
Currency and Payment Gateway Auto-Detection Service
Detects user location and determines best payment gateway + currency
"""
import httpx
import logging
from enum import Enum
from typing import Tuple, Optional, Dict

logger = logging.getLogger(__name__)


class GatewayConfig:
    """Paystack + Flutterwave gateway configuration"""
    
    # Country to currency mapping
    COUNTRY_CURRENCY_MAP = {
        "KE": "KES",  # Kenya
        "UG": "UGX",  # Uganda
        "NG": "NGN",  # Nigeria
        "GH": "GHS",  # Ghana
        "TZ": "TZS",  # Tanzania
    }
    
    # Country to gateway mapping
    COUNTRY_GATEWAY_MAP = {
        "KE": "paystack",      # Kenya → Paystack (M-Pesa support)
        "UG": "paystack",      # Uganda → Paystack
        "NG": "flutterwave",   # Nigeria → Flutterwave
        "GH": "flutterwave",   # Ghana → Flutterwave
        "TZ": "paystack",      # Tanzania → Paystack
    }
    
    # Currency to gateway mapping (for international users)
    CURRENCY_GATEWAY_MAP = {
        "KES": "paystack",
        "UGX": "paystack",
        "TZS": "paystack",
        "NGN": "flutterwave",
        "USD": "flutterwave",
        "GBP": "flutterwave",
        "EUR": "flutterwave",
    }
    
    # Supported currencies per gateway
    PAYSTACK_CURRENCIES = ["KES", "UGX", "NGN", "GHS", "TZS", "USD"]
    FLUTTERWAVE_CURRENCIES = ["USD", "EUR", "GBP", "NGN", "KES", "UGX", "GHS", "TZS"]


class CurrencyDetector:
    """Detects user location and suggests optimal payment gateway"""
    
    def __init__(self, ip_geolocation_api_key: Optional[str] = None):
        """
        Initialize currency detector
        
        Args:
            ip_geolocation_api_key: API key for IP geolocation service
        """
        self.ip_geolocation_api_key = ip_geolocation_api_key
        self.base_url = "https://ipapi.co"
    
    async def detect_from_ip(self, ip_address: str) -> Dict[str, str]:
        """
        Detect country and currency from IP address
        
        Args:
            ip_address: User's IP address
            
        Returns:
            Dict with country_code, currency, gateway, method
            
        Example:
            {
                "country_code": "KE",
                "currency": "KES",
                "gateway": "paystack",
                "method": "mpesa"
            }
        """
        try:
            async with httpx.AsyncClient() as client:
                # Using ipapi.co (free, no API key required for basic usage)
                response = await client.get(
                    f"{self.base_url}/{ip_address}/json/",
                    timeout=5.0
                )
                response.raise_for_status()
                data = response.json()
                
                country_code = data.get("country_code", "").upper()
                
                return self._determine_gateway(country_code)
        
        except Exception as e:
            logger.error(f"IP geolocation error: {e}")
            # Default to KES + Paystack on error
            return {
                "country_code": "KE",
                "currency": "KES",
                "gateway": "paystack",
                "method": "mpesa"
            }
    
    def detect_from_phone(self, phone_number: str) -> Dict[str, str]:
        """
        Detect country from phone number
        
        Args:
            phone_number: E.164 format (+254712345678)
            
        Returns:
            Dict with country_code, currency, gateway, method
        """
        # Extract country code from phone number
        if phone_number.startswith("+254"):
            country_code = "KE"
        elif phone_number.startswith("+256"):
            country_code = "UG"
        elif phone_number.startswith("+234"):
            country_code = "NG"
        else:
            # Default to Kenya
            country_code = "KE"
        
        return self._determine_gateway(country_code)
    
    def detect_from_country_code(self, country_code: str) -> Dict[str, str]:
        """
        Determine gateway from country code
        
        Args:
            country_code: ISO 2-letter country code (KE, US, etc.)
            
        Returns:
            Dict with country_code, currency, gateway, method
        """
        country_code = country_code.upper()
        return self._determine_gateway(country_code)
    
    def _determine_gateway(self, country_code: str) -> Dict[str, str]:
        """
        Internal method to determine gateway from country code
        
        Args:
            country_code: ISO 2-letter country code
            
        Returns:
            Gateway configuration dict
        """
        # Default to Kenya if unknown
        if country_code not in GatewayConfig.COUNTRY_CURRENCY_MAP:
            country_code = "KE"
        
        currency = GatewayConfig.COUNTRY_CURRENCY_MAP.get(country_code, "KES")
        gateway = GatewayConfig.COUNTRY_GATEWAY_MAP.get(country_code, "paystack")
        
        # Determine payment method based on gateway and country
        method = self._get_payment_method(gateway, country_code, currency)
        
        return {
            "country_code": country_code,
            "currency": currency,
            "gateway": gateway,
            "method": method
        }
    
    @staticmethod
    def _get_payment_method(gateway: str, country_code: str, currency: str) -> str:
        """
        Determine best payment method for gateway
        
        Args:
            gateway: paystack or flutterwave
            country_code: ISO country code
            currency: Currency code
            
        Returns:
            Payment method (mpesa, kes_card, usd_card)
        """
        if gateway == "paystack":
            # Paystack supports M-Pesa for Kenya
            if country_code == "KE" and currency == "KES":
                return "mpesa"  # M-Pesa default for Kenya
            else:
                return "kes_card"  # Local card
        else:
            # Flutterwave for international
            return "usd_card"
    
    @staticmethod
    def get_available_methods(country_code: str) -> list:
        """
        Get all available payment methods for a country
        
        Args:
            country_code: ISO country code
            
        Returns:
            List of available payment methods
        """
        methods = []
        
        if country_code == "KE":
            methods = ["mpesa", "kes_card"]
        else:
            methods = ["usd_card"]
        
        return methods
    
    @staticmethod
    def validate_currency_for_gateway(currency: str, gateway: str) -> bool:
        """
        Validate if currency is supported by gateway
        
        Args:
            currency: Currency code
            gateway: paystack or flutterwave
            
        Returns:
            True if supported, False otherwise
        """
        if gateway == "paystack":
            return currency in GatewayConfig.PAYSTACK_CURRENCIES
        elif gateway == "flutterwave":
            return currency in GatewayConfig.FLUTTERWAVE_CURRENCIES
        return False


class CurrencyExchange:
    """Handle currency conversion if needed"""
    
    # Static exchange rates (in production, use real-time rates)
    EXCHANGE_RATES = {
        ("KES", "USD"): 0.0077,   # 1 KES = 0.0077 USD
        ("USD", "KES"): 130.0,    # 1 USD = 130 KES
        ("UGX", "USD"): 0.00027,  # 1 UGX = 0.00027 USD
        ("USD", "UGX"): 3700.0,   # 1 USD = 3700 UGX
    }
    
    @staticmethod
    def convert(amount: float, from_currency: str, to_currency: str) -> float:
        """
        Convert amount from one currency to another
        
        Args:
            amount: Amount to convert
            from_currency: Source currency code
            to_currency: Target currency code
            
        Returns:
            Converted amount
            
        Example:
            convert(1000, "KES", "USD")  # 1000 KES to USD
        """
        if from_currency == to_currency:
            return amount
        
        rate_key = (from_currency, to_currency)
        
        if rate_key not in CurrencyExchange.EXCHANGE_RATES:
            raise ValueError(f"No exchange rate for {rate_key}")
        
        rate = CurrencyExchange.EXCHANGE_RATES[rate_key]
        return round(amount * rate, 2)


# Singleton instance
currency_detector = CurrencyDetector()