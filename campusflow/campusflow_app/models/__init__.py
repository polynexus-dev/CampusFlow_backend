from .department import Department
from .course import Course
from .classroom import Classroom
from .lecture import Lecture
from .schedule import Schedule
from .profile import (
    StudentProfile,
    TeachingStaffProfile,
    NonTeachingStaffProfile,
    ManagementProfile,
    AdministratorProfile,
    DepartmentHeadProfile,
)
from .attendance import Attendance
from .face_embedding import FaceEmbedding
from .attendance_log import FaceAttendanceLog
from .attendance_session import AttendanceSession
from .fraud_alert import FraudAlert
from .device_reset import DeviceResetRequest

# ── New Modules ──
from .audit import AuditLog
from .announcement import Announcement
from .leave import LeaveType, LeaveBalance, LeaveRequest
from .payroll import SalaryStructure, Payslip
from .exam import ExamType, Exam
from .assignment import Assignment
from .submission import AssignmentSubmission
from .manual_attendance_request import ManualAttendanceRequest

# ── Bus Tracking ──
from .bus_tracking import BusRoute, BusLocation, BusTrail, BusSubscription, BusAttendance

# ── Fees & Accounts ──
from .fees import (
    FeeCategory, FeeStructure, FeeStructureItem,
    StudentFeeInvoice, StudentFeeInvoiceItem, FeePayment
)


