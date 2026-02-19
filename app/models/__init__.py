# Import all models in correct order to avoid circular imports
from app.models.user import User, UserRole, UserPreference
from app.models.property import Property, Unit
from app.models.tenant import Tenant
from app.models.payment import Payment, Subscription, Invoice, PaymentGatewayLog

# Optional models - import only if they exist
try:
    from app.models.maintenance import MaintenanceRequest
except ImportError:
    MaintenanceRequest = None

try:
    from app.models.meter import MeterReading
except ImportError:
    MeterReading = None

# Staff and Attendance have circular relationships - import Staff first,
# then attendance models. SQLAlchemy resolves string references lazily.
try:
    from app.models.staff import Staff
except ImportError:
    Staff = None

try:
    from app.models.attendance import Attendance, LeaveRequest, AttendanceSummary
except ImportError:
    Attendance = None
    LeaveRequest = None
    AttendanceSummary = None

try:
    from app.models.incident import Incident
except ImportError:
    Incident = None

try:
    from app.models.task import Task
except ImportError:
    Task = None

try:
    from app.models.equipment import Equipment
except ImportError:
    Equipment = None

try:
    from app.models.lead import Lead, LeadStatus
except ImportError:
    Lead = None
    LeadStatus = None

try:
    from app.models.viewing import Viewing, ViewingStatus
except ImportError:
    Viewing = None
    ViewingStatus = None

try:
    from app.models.market import AreaMetrics
except ImportError:
    AreaMetrics = None

try:
    from app.models.workflow import Workflow, WorkflowAction, WorkflowLog
except ImportError:
    Workflow = None
    WorkflowAction = None
    WorkflowLog = None

try:
    from app.models.lease import Lease, LeaseClause, LeaseSignature
except ImportError:
    Lease = None
    LeaseClause = None
    LeaseSignature = None

try:
    from app.models.inspection import (
        Inspection, InspectionItem, InspectionMedia,
        InspectionMeterReading, InspectionStatus, InspectionType,
        InspectionTemplate, InspectionSignature, SeverityLevel
    )
except ImportError:
    Inspection = None
    InspectionItem = None
    InspectionMedia = None
    InspectionMeterReading = None
    InspectionStatus = None
    InspectionType = None
    InspectionTemplate = None
    InspectionSignature = None
    SeverityLevel = None

__all__ = [
    "User",
    "UserRole",
    "UserPreference",
    "Property",
    "Unit",
    "Tenant",
    "Payment",
    "Subscription",
    "Invoice",
    "PaymentGatewayLog",
]
