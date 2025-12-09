
from sqlalchemy import Column, Integer, String, ForeignKey, Float, Date, Enum as SQLEnum
from sqlalchemy.orm import relationship
from app.db.base import Base, TimestampMixin
from enum import Enum

class StaffDepartment(str, Enum):
    SECURITY = "security"
    GARDENING = "gardening"
    MAINTENANCE = "maintenance"

class Staff(Base, TimestampMixin):
    __tablename__ = "staff"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    department = Column(SQLEnum(StaffDepartment), nullable=False)
    position = Column(String(100), nullable=False)
    salary = Column(Float, nullable=False)
    start_date = Column(Date, nullable=False)
    supervisor_id = Column(Integer, ForeignKey("staff.id"), nullable=True)
