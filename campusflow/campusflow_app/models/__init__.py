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
    GuardianProfile,
)
from .attendance import Attendance
from .face_embedding import FaceEmbedding, FaceEmbeddingSample
from .attendance_log import FaceAttendanceLog
from .attendance_session import AttendanceSession
from .fraud_alert import FraudAlert
from .device_reset import DeviceResetRequest

# ── Academic Calendar & Curriculum ──
from .academics import AcademicYear, Term, Program, Regulation, Batch, Section
from .offerings import CourseOffering, StudentCourseRegistration
from .grading import (
    GradingScheme, GradeBand,
    CourseGradeAward, TermGradeSheet, StudentAcademicSummary,
)
from .outcomes import ProgramOutcome, CourseOutcome, POCOMapping

# ── New Modules ──
from .audit import AuditLog
from .announcement import Announcement
from .leave import LeaveType, LeaveBalance, LeaveRequest
from .payroll import SalaryStructure, Payslip
from .exam import ExamType, Exam
from .assignment import Assignment
from .submission import AssignmentSubmission
from .manual_attendance_request import ManualAttendanceRequest
from .attendance_correction import AttendanceCorrectionRequest

# ── Bus Tracking ──
from .bus_tracking import BusRoute, BusLocation, BusTrail, BusTrip, BusSubscription, BusAttendance, BusScanEvent

# ── Notifications ──
from .notification import Notification

# ── Fees & Accounts ──
from .fees import (
    FeeCategory, FeeStructure, FeeStructureItem,
    StudentFeeInvoice, StudentFeeInvoiceItem, FeePayment
)
from .payments import PaymentGatewayTransaction

# ── Module Subscriptions & Permissions ──
from .module_permissions import TenantModulePermission

# ── Competitive PARITY Modules ──
from .hostel import Hostel, HostelRoom, HostelAllocation
from .tpo import RecruitmentDrive, PlacementApplication
from .library import Book, BookCopy, BookIssue
from .inventory import InventoryCategory, InventoryItem, Supplier, InventoryTransaction
from .valuation import ValuationSession, ScannedPaper
from .result import StudentExamResult
from .result_correction import ResultCorrectionRequest
from .consent import StudentConsent
from .promotion import PromotionBatch, PromotionRecord
from .parent_link_request import ParentLinkRequest

# ── Paper Setting from Syllabus ──
from .question_bank import SyllabusTopic, Question, PaperBlueprintTopic, ExamQuestion

# ── Compliance & Accreditation ──
from .compliance import (
    ComplianceCertificateType, ComplianceCertificate,
    AccreditationCriterion, EvidenceItem,
)

# ── Financial Year & Ledger Foundation ──
from .finance import (
    FinancialYear, IncomeCategory, IncomeEntry, ExpenseCategory, ExpenseEntry, FixedAsset,
)

# ── CA Role & Audit Portal ──
from .audit_portal import AuditorProfile, AuditEngagement, AuditorAccessLog

# ── State Scholarship Reconciliation ──
from .scholarship import StateScholarshipScheme, StudentScholarshipRecord



