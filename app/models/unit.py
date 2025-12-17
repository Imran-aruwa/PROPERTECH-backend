# Unit model is defined in property.py to avoid circular imports
# Re-export for backward compatibility
from app.models.property import Unit

__all__ = ["Unit"]
