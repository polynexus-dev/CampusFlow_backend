from django.urls import path
from tenants.views import InvoiceListAPIView, InvoiceUploadReceiptAPIView
from campusflow_app.views.department import DepartmentView, DepartmentDetailView
from campusflow_app.views.users import (
    StudentUserProfileView, VerifyTokenView, StudentRegistrationView, StaffRegistrationView,
    MyObtainTokenPairView, LogoutAPIView, UserProfileView,
    ManagementUserProfileView, AdministratorUserProfileView,
    TeachingStaffUserProfileView, VerifyAccountView, ResendOTPView,
    ResetDeviceLockView, RequestBiometricResetView, PendingApprovalsView, ApproveUserView,
    DepartmentHeadUserProfileView, NonTeachingStaffUserProfileView,
    CollegeEmployeesListView, UserPermissionsDetailView, ActiveTenantSettingsView,
    GuardianConsentApprovalView, UserDataErasureView, UserWithdrawConsentView, UserGrantConsentView,
    StudentOnboardRequestOTPView, StudentOnboardVerifyPasswordView,
    ForgotPasswordRequestOTPView, ForgotPasswordVerifyOTPView, ForgotPasswordResetView
)
from campusflow_app.views.location import LocationDetailView
from campusflow_app.views.attendance import (
    AttendanceMarkView, AllAttendanceView,
    LectureCheckinByCodeView
)
from campusflow_app.views.face_attendance import (
    FaceRegistrationView, LivenessChallengeView,
    MarkAttendanceView, AttendanceHistoryView,
    StudentRequestManualAttendanceView, StudentManualRequestStatusView
)
from campusflow_app.views.lecturer_attendance import (
    LecturerCheckInView, LecturerStartSessionView,
    LecturerAttendanceStatusView, LecturerManualRequestsView,
    LecturerApproveManualRequestView, LecturerConductedHistoryView,
    LecturerBulkApproveManualRequestsView, LecturerDeviceResetRequestsView,
    LecturerApproveDeviceResetRequestView
)
from campusflow_app.views.classroom import ClassroomCreateView, CheckAttendanceView, ClassroomListView, ClassroomLocationValidationView
from campusflow_app.views.lecture import (
    LectureListCreateView, LectureDetailView, LectureByClassroomView,
    GenerateLectureCodeView
)

# ── New Module Imports ──
from campusflow_app.views.audit import AuditLogListView
from campusflow_app.views.announcement import AnnouncementListCreateView, AnnouncementDetailView
from campusflow_app.views.leave import (
    LeaveTypeListCreateView, LeaveTypeDetailView,
    LeaveBalanceView, LeaveRequestCreateView, LeaveRequestListView,
    LeaveRequestActionView, MyLeavesView
)
from campusflow_app.views.payroll import (
    SalaryStructureListView, SalaryStructureDetailView,
    GeneratePayslipView, BulkPayslipGenerationView, PayslipListView
)
from campusflow_app.views.exam import ExamTypeListCreateView, ExamListCreateView, ExamDetailView
from campusflow_app.views.course import CourseListCreateView, CourseDetailView
from campusflow_app.views.schedule import ScheduleListView, TeacherTodayScheduleView
from campusflow_app.views.timetable_generation import (
    GenerateTimetableView, TimetableGenerationRunViewSet,
    ApplyTimetableGenerationRunView, DiscardTimetableGenerationRunView,
)
from campusflow_app.views.attendance_correction import (
    GuardianCreateCorrectionRequestView, TeacherCorrectionRequestListView,
    TeacherCorrectionRequestActionView,
)
from campusflow_app.views.quick_create import QuickCreatePostView
from campusflow_app.views.enrollment import AdminEnrollStudentView, StudentConsentGrantView, EnrollmentStatsView
from campusflow_app.views.admissions import (
    LeadViewSet, LeadActivityViewSet, LeadMarkContactedView, LeadSubmitApplicationView,
    LeadAdmitView, LeadCloseView, LeadConvertToStudentView,
)
from campusflow_app.views.face_registration_queue import (
    FaceRegistrationQueueView, FaceRegistrationCaptureView, FaceRegistrationRetakeView,
)
from campusflow_app.views.promotion import PromoteClassView, PromoteClassRevertView
from campusflow_app.views.parent_link_request import (
    ParentLinkRequestCreateView, AdminParentLinkRequestListView, AdminParentLinkRequestActionView,
)
from campusflow_app.views.question_bank import (
    SyllabusTopicListCreateView, SyllabusTopicDetailView,
    QuestionBankListCreateView, QuestionDetailView,
)
from campusflow_app.views.outcomes import (
    ProgramOutcomeListCreateView, ProgramOutcomeDetailView,
    CourseOutcomeListCreateView, CourseOutcomeDetailView,
    POCOMappingListCreateView, POCOMappingDetailView,
    CourseOutcomeAttainmentView, ProgramOutcomeAttainmentView,
)
from campusflow_app.views.academics import (
    AcademicYearListCreateView, AcademicYearDetailView,
    TermListCreateView, TermDetailView,
    CurrentTermView, SetCurrentTermView,
)
from campusflow_app.views.curriculum import (
    ProgramListCreateView, ProgramDetailView,
    RegulationListCreateView, RegulationDetailView, RegulationCourseListView,
    BatchListCreateView, BatchDetailView,
    SectionListCreateView, SectionDetailView,
    GradingSchemeListView, GradingSchemeDetailView,
)
from campusflow_app.views.grading import PublishTermResultsView, StudentTranscriptView
from campusflow_app.views.paper_setting import (
    PaperBlueprintView, GeneratePaperView, ExamPaperView,
    ExamQuestionAddView, ExamQuestionReplaceView, ExamQuestionDetailView,
    FinalizePaperView, GeneratePaperSetsView, PaperSetsListView,
)
from campusflow_app.views.assignment import AssignmentListCreateView, AssignmentDetailView
from campusflow_app.views.submission import SubmissionListCreateView, SubmissionGradeView
from campusflow_app.views.analytics import (
    OverviewKPIView, AttendanceTrendsView, DepartmentPerformanceView,
    LeaveAnalyticsView, PayrollSummaryView, AtRiskStudentsView
)
from campusflow_app.views.bus_tracking import (
    BusRouteListCreateView, BusRouteDetailView,
    BusRouteQRView, BusRouteRegenQRView,
    BusLiveLocationsView, BusTrailView,
    BusSubscriptionListCreateView, BusSubscriptionDetailView,
    BusBoardingScanView, BusAttendanceListView,
    BusDriverDashboardView, BusSummaryStatsView,
    BusTripStartView, BusTripEndView, BusDriverTripStatsView,
    BusConductorScanStudentView, BusTripSummaryView, StudentIDQRView,
)
from campusflow_app.views.notifications import (
    NotificationListView, NotificationMarkReadView, NotificationUnreadCountView,
)
from campusflow_app.views.fees import (
    FeeCategoryViewSet, FeeStructureViewSet, StudentFeeInvoiceViewSet,
    BulkGenerateInvoicesView, RecordFeePaymentView, FeePaymentListView,
    FeeDashboardView
)
from campusflow_app.views.payments import (
    CreatePaymentOrderView, VerifyPaymentView, RazorpayWebhookView
)
from campusflow_app.views.module_permissions import (
    TenantSubscriptionView, RoleModulePermissionView, MyAllowedModulesView, CustomRolesView
)
from campusflow_app.views.hostel import HostelViewSet, HostelRoomViewSet, HostelAllocationViewSet
from campusflow_app.views.tpo import RecruitmentDriveViewSet, PlacementApplicationViewSet
from campusflow_app.views.library import BookViewSet, BookCopyViewSet, BookIssueViewSet
from campusflow_app.views.inventory import InventoryCategoryViewSet, InventoryItemViewSet, SupplierViewSet, InventoryTransactionViewSet
from campusflow_app.views.valuation import (
    ValuationSessionViewSet, ScannedPaperViewSet,
    ScannedPaperAISuggestView, ScannedPaperAISuggestionListView,
    AIGradingSuggestionApplyView, AIGradingSuggestionRejectView,
)
from campusflow_app.views.result import StudentExamResultViewSet, ExamClassStatsView, ExamPublishResultsView
from campusflow_app.views.result_correction import (
    ResultCorrectionRequestCreateView, HMCorrectionRequestListView, HMCorrectionRequestActionView,
)
from campusflow_app.views.syllabus_coverage import (
    MyOfferingsForCoverageView, OfferingCoverageChecklistView, HODOfferingCoverageListView,
)
from campusflow_app.views.compliance import (
    ComplianceCertificateTypeViewSet, ComplianceCertificateViewSet,
    AISHEAnnualReturnView, AICTEDisclosureView, NAACExtendedProfileView,
    AccreditationCriterionViewSet, EvidenceItemViewSet,
    SubmitEvidenceItemView, SignOffEvidenceItemView, SSRExportView,
    CriterionNarrativeDraftRequestView, AccreditationNarrativeDraftViewSet,
    NarrativeDraftApplyView, NarrativeDraftRejectView, NBASARExportView,
)
from campusflow_app.views.nirf import NIRFDataEntryViewSet, NIRFReportView
from campusflow_app.views.statutory_committee import (
    StatutoryCommitteeViewSet, CommitteeMembershipViewSet,
    CommitteeComplaintViewSet, CommitteeMeetingViewSet, CommitteeAnnualReportView,
)
from campusflow_app.views.finance import (
    FinancialYearViewSet, CloseFinancialYearView,
    IncomeCategoryViewSet, IncomeEntryViewSet,
    ExpenseCategoryViewSet, ExpenseEntryViewSet, FixedAssetViewSet,
)
from campusflow_app.views.audit_portal import (
    InviteAuditorView, AuditEngagementListView, RevokeAuditEngagementView, MyAuditEngagementsView,
    ReceiptsPaymentsStatementView, IncomeExpenditureStatementView, FixedAssetRegisterView,
    PayrollStatutorySummaryView, FeeReconciliationView, VendorLedgerView, DocumentVaultExportView,
    AssetsLiabilitiesScheduleView,
)
from campusflow_app.views.scholarship import StateScholarshipSchemeViewSet, StudentScholarshipRecordViewSet
from campusflow_app.views.progress import StudentProgressView, StudentTopicPerformanceView, StudentInsightView
from campusflow_app.views.contact import ContactEnquiryView
from campusflow_app.views.guardian import (
    ParentLinkChildView, ParentChildrenListView,
    ParentChildAttendanceView, ParentChildFeesView,
    ParentChildExamsView, ParentChildAssignmentsView
)


urlpatterns = [

    # ── Contact/Enquiry from Landing Page ────────────────────────────
    path('contact/', ContactEnquiryView.as_view(), name='contact_enquiry'),

    # ── Auth ─────────────────────────────────────────────────────────
    path('register/student/', StudentRegistrationView.as_view(), name='student_registration'),
    path('register/staff/', StaffRegistrationView.as_view(), name='staff_registration'),
    path('verify-account/', VerifyAccountView.as_view(), name='verify-account'),
    path('resend-otp/', ResendOTPView.as_view(), name='resend-otp'),
    path('student/onboard/request-otp/', StudentOnboardRequestOTPView.as_view(), name='student_onboard_request_otp'),
    path('student/onboard/verify-password/', StudentOnboardVerifyPasswordView.as_view(), name='student_onboard_verify_password'),
    path('user/forgot-password/request-otp/', ForgotPasswordRequestOTPView.as_view(), name='forgot_password_request_otp'),
    path('user/forgot-password/verify-otp/', ForgotPasswordVerifyOTPView.as_view(), name='forgot_password_verify_otp'),
    path('user/forgot-password/reset/', ForgotPasswordResetView.as_view(), name='forgot_password_reset'),
    path('login/', MyObtainTokenPairView.as_view(), name='token_obtain_pair'),
    path('logout/', LogoutAPIView.as_view(), name='logout'),
    path('token/verify/', VerifyTokenView.as_view(), name='verify-token'),
    path('student/reset-device-lock/', ResetDeviceLockView.as_view(), name='reset_device_lock'),
    path('student/request-biometric-reset/', RequestBiometricResetView.as_view(), name='request_biometric_reset'),
    
    # DPDP Consent/Compliance routes
    path('register/guardian-consent/', GuardianConsentApprovalView.as_view(), name='guardian_consent'),
    path('user/request-erasure/', UserDataErasureView.as_view(), name='user_data_erasure'),
    path('user/withdraw-consent/', UserWithdrawConsentView.as_view(), name='user_withdraw_consent'),
    path('user/grant-consent/', UserGrantConsentView.as_view(), name='user_grant_consent'),
    path('billing/invoices/', InvoiceListAPIView.as_view(), name='invoice_list'),
    path('billing/invoices/<int:pk>/upload-receipt/', InvoiceUploadReceiptAPIView.as_view(), name='invoice_upload_receipt'),

    # ── Approvals ──
    path('approvals/pending/', PendingApprovalsView.as_view(), name='pending_approvals'),
    path('approvals/action/', ApproveUserView.as_view(), name='approve_user_action'),

    # ── Profiles ─────────────────────────────────────────────────────
    # GET own profile (any authenticated user)
    path('user/', UserProfileView.as_view(), name='user_profile'),
    # GET / PATCH active tenant details & logo
    path('tenant/settings/', ActiveTenantSettingsView.as_view(), name='tenant_settings'),
    # GET all management profiles (Management / SaaS Admin only)
    path('management/user/', ManagementUserProfileView.as_view(), name='management_user_profile'),
    # GET all administrator profiles (Management / SaaS Admin only)
    path('administrator/user/', AdministratorUserProfileView.as_view(), name='administrator_user_profile'),
    # GET all teaching staff profiles (College Admins / SaaS Admin only)
    path('teaching-staff/user/', TeachingStaffUserProfileView.as_view(), name='teaching_staff_user_profile'),
    # GET all department head profiles (College Admins / SaaS Admin only)
    path('hod/user/', DepartmentHeadUserProfileView.as_view(), name='department_head_user_profile'),
    # GET all non-teaching support staff profiles (College Admins / SaaS Admin only)
    path('support-staff/user/', NonTeachingStaffUserProfileView.as_view(), name='non_teaching_staff_user_profile'),
    # GET all student profiles (Faculty and above only)
    path('student/user/', StudentUserProfileView.as_view(), name='student_user_profile'),

    # ── Department ────────────────────────────────────────────────────
    # GET list / POST create / DELETE all  (write: College Admins + SaaS Admin)
    path('department/', DepartmentView.as_view(), name='DepartmentView'),
    # GET detail / POST update / DELETE one
    path('department/<int:pk>/', DepartmentDetailView.as_view(), name='DepartmentDetailView'),

    # ── Academic Calendar ─────────────────────────────────────────────
    # GET list (any auth) / POST create (College Admins + SaaS Admin)
    path('academics/years/', AcademicYearListCreateView.as_view(), name='academic-year-list'),
    path('academics/years/<int:pk>/', AcademicYearDetailView.as_view(), name='academic-year-detail'),
    path('academics/terms/', TermListCreateView.as_view(), name='term-list'),
    path('academics/terms/<int:pk>/', TermDetailView.as_view(), name='term-detail'),
    # The resolver that replaces hardcoded semester strings. Self-provisioning,
    # so it never 404s on a tenant that has no calendar yet.
    path('academics/current-term/', CurrentTermView.as_view(), name='current-term'),
    path('academics/current-term/set/', SetCurrentTermView.as_view(), name='current-term-set'),

    # ── Curriculum Structure ──────────────────────────────────────────
    # Program > Regulation > Batch > Section. A batch owns the regulation, and
    # students inherit it from their batch rather than choosing one.
    path('academics/programs/', ProgramListCreateView.as_view(), name='program-list'),
    path('academics/programs/<int:pk>/', ProgramDetailView.as_view(), name='program-detail'),
    path('academics/regulations/', RegulationListCreateView.as_view(), name='regulation-list'),
    path('academics/regulations/<int:pk>/', RegulationDetailView.as_view(), name='regulation-detail'),
    path('academics/regulations/<int:pk>/courses/', RegulationCourseListView.as_view(), name='regulation-courses'),
    path('academics/batches/', BatchListCreateView.as_view(), name='batch-list'),
    path('academics/batches/<int:pk>/', BatchDetailView.as_view(), name='batch-detail'),
    path('academics/sections/', SectionListCreateView.as_view(), name='section-list'),
    path('academics/sections/<int:pk>/', SectionDetailView.as_view(), name='section-detail'),
    path('academics/grading-schemes/', GradingSchemeListView.as_view(), name='grading-scheme-list'),
    path('academics/grading-schemes/<int:pk>/', GradingSchemeDetailView.as_view(), name='grading-scheme-detail'),
    path('academics/terms/<int:pk>/publish-results/', PublishTermResultsView.as_view(), name='publish-term-results'),
    path('academics/students/<int:pk>/transcript/', StudentTranscriptView.as_view(), name='student-transcript'),
    path('academics/my-transcript/', StudentTranscriptView.as_view(), name='my-transcript'),

    # ── Location ──────────────────────────────────────────────────────
    # GET list (any auth) / POST create (College Admins+) / DELETE (College Admins+)
    path('location/', LocationDetailView.as_view(), name='location_detail'),

    # ── Attendance ────────────────────────────────────────────────────
    # GET all attendance records with optional filters (Faculty and above only)
    path('attendance/all/', AllAttendanceView.as_view(), name='all-attendance'),
    # POST manually mark a student's attendance (Faculty and above only)
    path('attendance/mark/', AttendanceMarkView.as_view(), name='attendance-mark'),
    # POST mark attendance using random code and geofence
    path('attendance/lecture-checkin/', LectureCheckinByCodeView.as_view(), name='lecture-checkin-by-code'),

    # ── Face Attendance ──
    path('register-face/', FaceRegistrationView.as_view(), name='register-face'),
    path('liveness-challenge/', LivenessChallengeView.as_view(), name='liveness-challenge'),
    path('mark-attendance/', MarkAttendanceView.as_view(), name='mark-attendance'),
    path('attendance-history/', AttendanceHistoryView.as_view(), name='attendance-history'),
    path('student/request-manual-attendance/', StudentRequestManualAttendanceView.as_view(), name='student-request-manual-attendance'),
    path('student/manual-request-status/', StudentManualRequestStatusView.as_view(), name='student-manual-request-status'),

    # ── Lecturer Attendance Session & Approvals ──
    path('lecturer/check-in/', LecturerCheckInView.as_view(), name='lecturer-check-in'),
    path('lecturer/start-attendance/', LecturerStartSessionView.as_view(), name='lecturer-start-attendance'),
    path('lecturer/status/', LecturerAttendanceStatusView.as_view(), name='lecturer-status'),
    path('lecturer/manual-requests/', LecturerManualRequestsView.as_view(), name='lecturer-manual-requests'),
    path('lecturer/approve-manual-request/', LecturerApproveManualRequestView.as_view(), name='lecturer-approve-manual-request'),
    path('lecturer/bulk-approve-manual-requests/', LecturerBulkApproveManualRequestsView.as_view(), name='lecturer-bulk-approve-manual-requests'),
    path('lecturer/device-resets/', LecturerDeviceResetRequestsView.as_view(), name='lecturer-device-resets'),
    path('lecturer/approve-device-reset/', LecturerApproveDeviceResetRequestView.as_view(), name='lecturer-approve-device-reset'),
    path('lecturer/conducted-history/', LecturerConductedHistoryView.as_view(), name='lecturer-conducted-history'),

    # ── Classroom ─────────────────────────────────────────────────────
    # POST create (College Admins+ only)
    path('classroom/', ClassroomCreateView.as_view(), name='ClassroomCreateView'),
    path('classrooms/', ClassroomListView.as_view(), name='classroom-list'),
    path('attendance/check/', CheckAttendanceView.as_view(), name='CheckAttendanceView'),
    path('validate-location/', ClassroomLocationValidationView.as_view(), name='validate-location'),

    # ── Lecture ───────────────────────────────────────────────────────
    # GET list (any auth) / POST create (Faculty and above — NOT students)
    path('lectures/', LectureListCreateView.as_view(), name='lecture-list-create'),
    # GET / PUT / PATCH / DELETE (Faculty own, Admins any)
    path('lectures/<int:pk>/', LectureDetailView.as_view(), name='lecture-detail'),
    # GET lectures for a classroom (any auth)
    path('classrooms/<int:classroom_id>/lectures/', LectureByClassroomView.as_view(), name='lectures-by-classroom'),
    # POST generate random code for a lecture
    path('lectures/<int:pk>/generate-code/', GenerateLectureCodeView.as_view(), name='generate-lecture-code'),

    # ── Permissions & Employees (College Admin) ─────────────────────────
    path('college/employees/', CollegeEmployeesListView.as_view(), name='college-employees-list'),
    path('college/user-permissions/<int:user_id>/', UserPermissionsDetailView.as_view(), name='user-permissions-detail'),

    # ══════════════════════════════════════════════════════════════════
    # NEW MODULES
    # ══════════════════════════════════════════════════════════════════

    # ── Audit Logs ────────────────────────────────────────────────────
    path('audit-logs/', AuditLogListView.as_view(), name='audit-logs'),

    # ── Announcements ─────────────────────────────────────────────────
    path('announcements/', AnnouncementListCreateView.as_view(), name='announcement-list-create'),
    path('announcements/<int:pk>/', AnnouncementDetailView.as_view(), name='announcement-detail'),

    # ── Leave Management ──────────────────────────────────────────────
    path('leave/types/', LeaveTypeListCreateView.as_view(), name='leave-type-list-create'),
    path('leave/types/<int:pk>/', LeaveTypeDetailView.as_view(), name='leave-type-detail'),
    path('leave/balance/', LeaveBalanceView.as_view(), name='leave-balance'),
    path('leave/request/', LeaveRequestCreateView.as_view(), name='leave-request-create'),
    path('leave/requests/', LeaveRequestListView.as_view(), name='leave-request-list'),
    path('leave/action/', LeaveRequestActionView.as_view(), name='leave-request-action'),
    path('leave/my/', MyLeavesView.as_view(), name='my-leaves'),

    # ── Payroll ───────────────────────────────────────────────────────
    path('payroll/structures/', SalaryStructureListView.as_view(), name='salary-structure-list'),
    path('payroll/structures/<int:user_id>/', SalaryStructureDetailView.as_view(), name='salary-structure-detail'),
    path('payroll/generate/', GeneratePayslipView.as_view(), name='generate-payslip'),
    path('payroll/generate-bulk/', BulkPayslipGenerationView.as_view(), name='bulk-generate-payslips'),
    path('payroll/payslips/', PayslipListView.as_view(), name='payslip-list'),

    # ── Exam / Timetable ─────────────────────────────────────────────
    path('exams/types/', ExamTypeListCreateView.as_view(), name='exam-type-list-create'),
    path('exams/', ExamListCreateView.as_view(), name='exam-list-create'),
    path('exams/<int:pk>/', ExamDetailView.as_view(), name='exam-detail'),
    path('courses/', CourseListCreateView.as_view(), name='course-list-create'),
    path('courses/<int:pk>/', CourseDetailView.as_view(), name='course-detail'),
    path('schedules/', ScheduleListView.as_view(), name='schedule-list'),
    path('schedule/today/', TeacherTodayScheduleView.as_view(), name='schedule-today'),

    # Timetable generation (OR-Tools CP-SAT)
    path('timetable/generate/', GenerateTimetableView.as_view(), name='timetable-generate'),
    path('timetable-generation-runs/', TimetableGenerationRunViewSet.as_view({'get': 'list'}), name='timetablegenerationrun-list'),
    path('timetable-generation-runs/<int:pk>/', TimetableGenerationRunViewSet.as_view({'get': 'retrieve'}), name='timetablegenerationrun-detail'),
    path('timetable-generation-runs/<int:pk>/apply/', ApplyTimetableGenerationRunView.as_view(), name='timetablegenerationrun-apply'),
    path('timetable-generation-runs/<int:pk>/discard/', DiscardTimetableGenerationRunView.as_view(), name='timetablegenerationrun-discard'),

    # ── Attendance Correction Requests ───────────────────────────────
    path('attendance/corrections/', GuardianCreateCorrectionRequestView.as_view(), name='attendance-correction-create'),
    path('attendance/corrections/list/', TeacherCorrectionRequestListView.as_view(), name='attendance-correction-list'),
    path('attendance/corrections/<int:pk>/action/', TeacherCorrectionRequestActionView.as_view(), name='attendance-correction-action'),

    # ── Analytics ─────────────────────────────────────────────────────
    path('analytics/overview/', OverviewKPIView.as_view(), name='analytics-overview'),
    path('analytics/attendance-trends/', AttendanceTrendsView.as_view(), name='analytics-attendance-trends'),
    path('analytics/department-performance/', DepartmentPerformanceView.as_view(), name='analytics-department-performance'),
    path('analytics/leave/', LeaveAnalyticsView.as_view(), name='analytics-leave'),
    path('analytics/payroll/', PayrollSummaryView.as_view(), name='analytics-payroll'),
    path('analytics/student-progress/', StudentProgressView.as_view(), name='analytics-student-progress'),
    path('analytics/student-topic-performance/', StudentTopicPerformanceView.as_view(), name='analytics-student-topic-performance'),
    path('analytics/student-insight/', StudentInsightView.as_view(), name='analytics-student-insight'),
    path('analytics/at-risk-students/', AtRiskStudentsView.as_view(), name='analytics-at-risk-students'),

    # ── Assignments ──────────────────────────────────────────────────
    path('assignments/', AssignmentListCreateView.as_view(), name='assignment-list-create'),
    path('assignments/<int:pk>/', AssignmentDetailView.as_view(), name='assignment-detail'),
    path('assignments/<int:assignment_id>/submissions/', SubmissionListCreateView.as_view(), name='submission-list-create'),
    path('submissions/<int:pk>/grade/', SubmissionGradeView.as_view(), name='submission-grade'),
    path('posts/quick-create/', QuickCreatePostView.as_view(), name='posts-quick-create'),

    # ── Admin Enrollment & Consent ───────────────────────────────────
    path('students/enroll/', AdminEnrollStudentView.as_view(), name='admin-enroll-student'),
    path('students/enrollment-stats/', EnrollmentStatsView.as_view(), name='enrollment-stats'),
    path('consents/<int:pk>/grant/', StudentConsentGrantView.as_view(), name='consent-grant'),

    # Admissions / CRM
    path('leads/', LeadViewSet.as_view({'get': 'list', 'post': 'create'}), name='lead-list'),
    path('leads/<int:pk>/', LeadViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='lead-detail'),
    path('lead-activities/', LeadActivityViewSet.as_view({'get': 'list', 'post': 'create'}), name='leadactivity-list'),
    path('lead-activities/<int:pk>/', LeadActivityViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='leadactivity-detail'),
    path('leads/<int:pk>/mark-contacted/', LeadMarkContactedView.as_view(), name='lead-mark-contacted'),
    path('leads/<int:pk>/submit-application/', LeadSubmitApplicationView.as_view(), name='lead-submit-application'),
    path('leads/<int:pk>/admit/', LeadAdmitView.as_view(), name='lead-admit'),
    path('leads/<int:pk>/close/', LeadCloseView.as_view(), name='lead-close'),
    path('leads/<int:pk>/convert/', LeadConvertToStudentView.as_view(), name='lead-convert'),

    # ── Face Registration Queue (Admin) ──────────────────────────────
    path('face-registration/queue/', FaceRegistrationQueueView.as_view(), name='face-registration-queue'),
    path('face-registration/<int:student_id>/capture/', FaceRegistrationCaptureView.as_view(), name='face-registration-capture'),
    path('face-registration/<int:student_id>/retake/<str:angle>/', FaceRegistrationRetakeView.as_view(), name='face-registration-retake'),

    # ── Promote Class (year-end) ─────────────────────────────────────
    path('students/promote/', PromoteClassView.as_view(), name='students-promote'),
    path('students/promote/<int:batch_id>/revert/', PromoteClassRevertView.as_view(), name='students-promote-revert'),

    # ── Parent Link Manager (Admin) ──────────────────────────────────
    path('parent-link-requests/', ParentLinkRequestCreateView.as_view(), name='parent-link-request-create'),
    path('parent-link-requests/list/', AdminParentLinkRequestListView.as_view(), name='parent-link-request-list'),
    path('parent-link-requests/<int:pk>/action/', AdminParentLinkRequestActionView.as_view(), name='parent-link-request-action'),

    # ── Syllabus & Question Bank ──────────────────────────────────────
    path('courses/<int:course_id>/syllabus-topics/', SyllabusTopicListCreateView.as_view(), name='syllabus-topic-list'),
    path('syllabus-topics/<int:pk>/', SyllabusTopicDetailView.as_view(), name='syllabus-topic-detail'),
    path('courses/<int:course_id>/questions/', QuestionBankListCreateView.as_view(), name='question-bank-list'),
    path('questions/<int:pk>/', QuestionDetailView.as_view(), name='question-bank-detail'),

    # ── Outcome-Based Education: PO / CO / CO-PO Matrix ────────────────
    path('academics/programs/<int:program_id>/outcomes/', ProgramOutcomeListCreateView.as_view(), name='program-outcome-list'),
    path('academics/program-outcomes/<int:pk>/', ProgramOutcomeDetailView.as_view(), name='program-outcome-detail'),
    path('courses/<int:course_id>/outcomes/', CourseOutcomeListCreateView.as_view(), name='course-outcome-list'),
    path('course-outcomes/<int:pk>/', CourseOutcomeDetailView.as_view(), name='course-outcome-detail'),
    path('course-outcomes/<int:course_outcome_id>/po-mappings/', POCOMappingListCreateView.as_view(), name='po-co-mapping-list'),
    path('po-mappings/<int:pk>/', POCOMappingDetailView.as_view(), name='po-co-mapping-detail'),
    path('courses/<int:course_id>/outcome-attainment/', CourseOutcomeAttainmentView.as_view(), name='course-outcome-attainment'),
    path('academics/programs/<int:program_id>/outcome-attainment/', ProgramOutcomeAttainmentView.as_view(), name='program-outcome-attainment'),
    path('academics/programs/<int:program_id>/nba-sar-export/', NBASARExportView.as_view(), name='program-nba-sar-export'),

    # ── Paper Setting from Syllabus ───────────────────────────────────
    path('exams/<int:pk>/blueprint/', PaperBlueprintView.as_view(), name='exam-paper-blueprint'),
    path('exams/<int:pk>/paper/generate/', GeneratePaperView.as_view(), name='exam-paper-generate'),
    path('exams/<int:pk>/paper/generate-sets/', GeneratePaperSetsView.as_view(), name='exam-paper-generate-sets'),
    path('exams/<int:pk>/paper/sets/', PaperSetsListView.as_view(), name='exam-paper-sets'),
    path('exams/<int:pk>/paper/', ExamPaperView.as_view(), name='exam-paper'),
    path('exams/<int:pk>/paper/questions/', ExamQuestionAddView.as_view(), name='exam-paper-question-add'),
    path('exams/<int:pk>/paper/questions/<int:exam_question_id>/replace/', ExamQuestionReplaceView.as_view(), name='exam-paper-question-replace'),
    path('exams/<int:pk>/paper/questions/<int:exam_question_id>/', ExamQuestionDetailView.as_view(), name='exam-paper-question-detail'),
    path('exams/<int:pk>/paper/finalize/', FinalizePaperView.as_view(), name='exam-paper-finalize'),

    # ── Bus Tracking ─────────────────────────────────────────────────
    # Admin: route management
    path('bus/routes/', BusRouteListCreateView.as_view(), name='bus-route-list'),
    path('bus/routes/<int:pk>/', BusRouteDetailView.as_view(), name='bus-route-detail'),
    path('bus/routes/<int:pk>/qr/', BusRouteQRView.as_view(), name='bus-route-qr'),
    path('bus/routes/<int:pk>/regen-qr/', BusRouteRegenQRView.as_view(), name='bus-route-regen-qr'),
    # Admin: subscription management
    path('bus/subscriptions/', BusSubscriptionListCreateView.as_view(), name='bus-subscription-list'),
    path('bus/subscriptions/<int:pk>/', BusSubscriptionDetailView.as_view(), name='bus-subscription-detail'),
    # Admin: live tracking & trail
    path('bus/live/', BusLiveLocationsView.as_view(), name='bus-live-locations'),
    path('bus/trail/<int:driver_id>/', BusTrailView.as_view(), name='bus-trail'),
    # Admin: attendance log
    path('bus/attendance/', BusAttendanceListView.as_view(), name='bus-attendance-list'),
    # Student: board the bus (QR scan)
    path('bus/scan/', BusBoardingScanView.as_view(), name='bus-boarding-scan'),
    path('bus/summary-stats/', BusSummaryStatsView.as_view(), name='bus-summary-stats'),
    # Conductor: scan a student's ID card (board/alight)
    path('bus/conductor/scan-student/', BusConductorScanStudentView.as_view(), name='bus-conductor-scan-student'),
    path('bus/driver/trip/<int:pk>/summary/', BusTripSummaryView.as_view(), name='bus-trip-summary'),
    path('bus/student/<int:pk>/id-card-qr/', StudentIDQRView.as_view(), name='bus-student-id-qr'),

    # ── Notifications ────────────────────────────────────────────────
    path('notifications/', NotificationListView.as_view(), name='notification-list'),
    path('notifications/<int:pk>/read/', NotificationMarkReadView.as_view(), name='notification-mark-read'),
    path('notifications/unread-count/', NotificationUnreadCountView.as_view(), name='notification-unread-count'),


    # ── Fees & Accounts ──────────────────────────────────────────────
    path('fees/categories/', FeeCategoryViewSet.as_view({'get': 'list', 'post': 'create'}), name='fee-category-list'),
    path('fees/categories/<int:pk>/', FeeCategoryViewSet.as_view({'get': 'retrieve', 'put': 'update', 'delete': 'destroy'}), name='fee-category-detail'),
    path('fees/structures/', FeeStructureViewSet.as_view({'get': 'list', 'post': 'create'}), name='fee-structure-list'),
    path('fees/structures/<int:pk>/', FeeStructureViewSet.as_view({'get': 'retrieve', 'put': 'update', 'delete': 'destroy'}), name='fee-structure-detail'),
    path('fees/invoices/', StudentFeeInvoiceViewSet.as_view({'get': 'list', 'post': 'create'}), name='student-fee-invoice-list'),
    path('fees/invoices/<int:pk>/', StudentFeeInvoiceViewSet.as_view({'get': 'retrieve', 'put': 'update', 'delete': 'destroy'}), name='student-fee-invoice-detail'),
    path('fees/invoices/bulk-generate/', BulkGenerateInvoicesView.as_view(), name='fee-invoice-bulk-generate'),
    path('fees/invoices/<int:invoice_id>/pay/', RecordFeePaymentView.as_view(), name='fee-invoice-pay'),
    path('fees/payments/', FeePaymentListView.as_view(), name='fee-payment-list'),
    path('fees/dashboard/', FeeDashboardView.as_view(), name='fee-dashboard'),

    # ── Online Payments (Gateway) ───────────────────────────────────
    path('payments/orders/', CreatePaymentOrderView.as_view(), name='payment-create-order'),
    path('payments/verify/', VerifyPaymentView.as_view(), name='payment-verify'),
    path('payments/webhook/razorpay/', RazorpayWebhookView.as_view(), name='payment-webhook-razorpay'),
    # Conductor/Driver dashboard
    path('bus/driver/dashboard/', BusDriverDashboardView.as_view(), name='bus-driver-dashboard'),
    path('bus/driver/trip/start/', BusTripStartView.as_view(), name='bus-trip-start'),
    path('bus/driver/trip/end/', BusTripEndView.as_view(), name='bus-trip-end'),
    path('bus/driver/trip-stats/', BusDriverTripStatsView.as_view(), name='bus-trip-stats'),

    # ── Module Subscriptions & Permissions ───────────────────────────
    path('tenant/subscriptions/<int:tenant_id>/', TenantSubscriptionView.as_view(), name='tenant-subscription'),
    path('tenant/module-permissions/', RoleModulePermissionView.as_view(), name='role-module-permissions'),
    path('tenant/roles/', CustomRolesView.as_view(), name='tenant-custom-roles'),
    path('user/allowed-modules/', MyAllowedModulesView.as_view(), name='user-allowed-modules'),

    # ── Competitive PARITY Modules ──
    # Hostel Management
    path('hostels/', HostelViewSet.as_view({'get': 'list', 'post': 'create'}), name='hostel-list'),
    path('hostels/<int:pk>/', HostelViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='hostel-detail'),
    path('hostel-rooms/', HostelRoomViewSet.as_view({'get': 'list', 'post': 'create'}), name='hostelroom-list'),
    path('hostel-rooms/<int:pk>/', HostelRoomViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='hostelroom-detail'),
    path('hostel-allocations/', HostelAllocationViewSet.as_view({'get': 'list', 'post': 'create'}), name='hostelallocation-list'),
    path('hostel-allocations/<int:pk>/', HostelAllocationViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='hostelallocation-detail'),

    # Training & Placement
    path('recruitment-drives/', RecruitmentDriveViewSet.as_view({'get': 'list', 'post': 'create'}), name='recruitmentdrive-list'),
    path('recruitment-drives/<int:pk>/', RecruitmentDriveViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='recruitmentdrive-detail'),
    path('placement-applications/', PlacementApplicationViewSet.as_view({'get': 'list', 'post': 'create'}), name='placementapplication-list'),
    path('placement-applications/<int:pk>/', PlacementApplicationViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='placementapplication-detail'),

    # Library Management
    path('books/', BookViewSet.as_view({'get': 'list', 'post': 'create'}), name='book-list'),
    path('books/<int:pk>/', BookViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='book-detail'),
    path('book-copies/', BookCopyViewSet.as_view({'get': 'list', 'post': 'create'}), name='bookcopy-list'),
    path('book-copies/<int:pk>/', BookCopyViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='bookcopy-detail'),
    path('book-issues/', BookIssueViewSet.as_view({'get': 'list', 'post': 'create'}), name='bookissue-list'),
    path('book-issues/<int:pk>/', BookIssueViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='bookissue-detail'),

    # Inventory & Store
    path('inventory-categories/', InventoryCategoryViewSet.as_view({'get': 'list', 'post': 'create'}), name='inventorycategory-list'),
    path('inventory-categories/<int:pk>/', InventoryCategoryViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='inventorycategory-detail'),
    path('inventory-items/', InventoryItemViewSet.as_view({'get': 'list', 'post': 'create'}), name='inventoryitem-list'),
    path('inventory-items/<int:pk>/', InventoryItemViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='inventoryitem-detail'),
    path('suppliers/', SupplierViewSet.as_view({'get': 'list', 'post': 'create'}), name='supplier-list'),
    path('suppliers/<int:pk>/', SupplierViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='supplier-detail'),
    path('inventory-transactions/', InventoryTransactionViewSet.as_view({'get': 'list', 'post': 'create'}), name='inventorytransaction-list'),
    path('inventory-transactions/<int:pk>/', InventoryTransactionViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='inventorytransaction-detail'),

    # Digital Valuation
    path('valuation-sessions/', ValuationSessionViewSet.as_view({'get': 'list', 'post': 'create'}), name='valuationsession-list'),
    path('valuation-sessions/<int:pk>/', ValuationSessionViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='valuationsession-detail'),
    path('scanned-papers/', ScannedPaperViewSet.as_view({'get': 'list', 'post': 'create'}), name='scannedpaper-list'),
    path('scanned-papers/<int:pk>/', ScannedPaperViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='scannedpaper-detail'),
    path('scanned-papers/<int:pk>/ai-suggest/', ScannedPaperAISuggestView.as_view(), name='scannedpaper-ai-suggest'),
    path('scanned-papers/<int:pk>/ai-suggestions/', ScannedPaperAISuggestionListView.as_view(), name='scannedpaper-ai-suggestions'),
    path('ai-suggestions/<int:pk>/apply/', AIGradingSuggestionApplyView.as_view(), name='ai-suggestion-apply'),
    path('ai-suggestions/<int:pk>/reject/', AIGradingSuggestionRejectView.as_view(), name='ai-suggestion-reject'),

    # Student Exam Results
    path('exam-results/', StudentExamResultViewSet.as_view({'get': 'list', 'post': 'create'}), name='studentexamresult-list'),
    path('exam-results/<int:pk>/', StudentExamResultViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='studentexamresult-detail'),
    path('exams/<int:pk>/class-stats/', ExamClassStatsView.as_view(), name='exam-class-stats'),
    path('exams/<int:pk>/publish-results/', ExamPublishResultsView.as_view(), name='exam-publish-results'),
    path('results/corrections/', ResultCorrectionRequestCreateView.as_view(), name='result-correction-create'),
    path('results/corrections/list/', HMCorrectionRequestListView.as_view(), name='result-correction-list'),
    path('results/corrections/<int:pk>/action/', HMCorrectionRequestActionView.as_view(), name='result-correction-action'),

    path('syllabus-coverage/my-offerings/', MyOfferingsForCoverageView.as_view(), name='syllabus-coverage-my-offerings'),
    path('syllabus-coverage/offerings/<int:offering_id>/', OfferingCoverageChecklistView.as_view(), name='syllabus-coverage-checklist'),
    path('syllabus-coverage/department-offerings/', HODOfferingCoverageListView.as_view(), name='syllabus-coverage-department'),

    # ── Parent / Guardian Endpoints ──
    path('parent/children/', ParentChildrenListView.as_view(), name='parent-children-list'),
    path('parent/children/link/', ParentLinkChildView.as_view(), name='parent-link-child'),
    path('parent/children/<int:student_id>/attendance/', ParentChildAttendanceView.as_view(), name='parent-child-attendance'),
    path('parent/children/<int:student_id>/fees/', ParentChildFeesView.as_view(), name='parent-child-fees'),
    path('parent/children/<int:student_id>/exams/', ParentChildExamsView.as_view(), name='parent-child-exams'),
    path('parent/children/<int:student_id>/assignments/', ParentChildAssignmentsView.as_view(), name='parent-child-assignments'),

    # Compliance & Accreditation — Certificate & License Vault (P1)
    path('compliance-certificate-types/', ComplianceCertificateTypeViewSet.as_view({'get': 'list', 'post': 'create'}), name='compliancecertificatetype-list'),
    path('compliance-certificate-types/<int:pk>/', ComplianceCertificateTypeViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='compliancecertificatetype-detail'),
    path('compliance-certificates/', ComplianceCertificateViewSet.as_view({'get': 'list', 'post': 'create'}), name='compliancecertificate-list'),
    path('compliance-certificates/<int:pk>/', ComplianceCertificateViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='compliancecertificate-detail'),

    # Financial Year & Ledger Foundation (P2)
    path('financial-years/', FinancialYearViewSet.as_view({'get': 'list', 'post': 'create'}), name='financialyear-list'),
    path('financial-years/<int:pk>/', FinancialYearViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='financialyear-detail'),
    path('financial-years/<int:pk>/close/', CloseFinancialYearView.as_view(), name='financialyear-close'),
    path('income-categories/', IncomeCategoryViewSet.as_view({'get': 'list', 'post': 'create'}), name='incomecategory-list'),
    path('income-categories/<int:pk>/', IncomeCategoryViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='incomecategory-detail'),
    path('income-entries/', IncomeEntryViewSet.as_view({'get': 'list', 'post': 'create'}), name='incomeentry-list'),
    path('income-entries/<int:pk>/', IncomeEntryViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='incomeentry-detail'),
    path('expense-categories/', ExpenseCategoryViewSet.as_view({'get': 'list', 'post': 'create'}), name='expensecategory-list'),
    path('expense-categories/<int:pk>/', ExpenseCategoryViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='expensecategory-detail'),
    path('expense-entries/', ExpenseEntryViewSet.as_view({'get': 'list', 'post': 'create'}), name='expenseentry-list'),
    path('expense-entries/<int:pk>/', ExpenseEntryViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='expenseentry-detail'),
    path('fixed-assets/', FixedAssetViewSet.as_view({'get': 'list', 'post': 'create'}), name='fixedasset-list'),
    path('fixed-assets/<int:pk>/', FixedAssetViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='fixedasset-detail'),

    # CA Role & Access Control (P3)
    path('audit-portal/invite-auditor/', InviteAuditorView.as_view(), name='audit-portal-invite-auditor'),
    path('audit-portal/engagements/', AuditEngagementListView.as_view(), name='audit-portal-engagement-list'),
    path('audit-portal/engagements/<int:pk>/revoke/', RevokeAuditEngagementView.as_view(), name='audit-portal-engagement-revoke'),
    path('audit-portal/my-engagements/', MyAuditEngagementsView.as_view(), name='audit-portal-my-engagements'),

    # CA Audit Portal — the reports themselves (P4)
    path('audit-portal/reports/receipts-payments/', ReceiptsPaymentsStatementView.as_view(), name='audit-portal-receipts-payments'),
    path('audit-portal/reports/income-expenditure/', IncomeExpenditureStatementView.as_view(), name='audit-portal-income-expenditure'),
    path('audit-portal/reports/fixed-asset-register/', FixedAssetRegisterView.as_view(), name='audit-portal-fixed-asset-register'),
    path('audit-portal/reports/payroll-statutory-summary/', PayrollStatutorySummaryView.as_view(), name='audit-portal-payroll-statutory-summary'),
    path('audit-portal/reports/fee-reconciliation/', FeeReconciliationView.as_view(), name='audit-portal-fee-reconciliation'),
    path('audit-portal/reports/vendor-ledger/', VendorLedgerView.as_view(), name='audit-portal-vendor-ledger'),
    path('audit-portal/document-vault/', DocumentVaultExportView.as_view(), name='audit-portal-document-vault'),
    path('audit-portal/reports/assets-liabilities-schedule/', AssetsLiabilitiesScheduleView.as_view(), name='audit-portal-assets-liabilities-schedule'),

    # Accreditation Reporting — Quick Wins (P5)
    path('compliance-center/reports/aishe-annual-return/', AISHEAnnualReturnView.as_view(), name='compliance-center-aishe'),
    path('compliance-center/reports/aicte-disclosure/', AICTEDisclosureView.as_view(), name='compliance-center-aicte'),
    path('compliance-center/reports/naac-extended-profile/', NAACExtendedProfileView.as_view(), name='compliance-center-naac-profile'),

    # NIRF Ranking Data Compilation
    path('nirf-data-entries/', NIRFDataEntryViewSet.as_view({'get': 'list', 'post': 'create'}), name='nirfdataentry-list'),
    path('nirf-data-entries/<int:pk>/', NIRFDataEntryViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='nirfdataentry-detail'),
    path('compliance-center/reports/nirf-data-compilation/', NIRFReportView.as_view(), name='compliance-center-nirf'),

    # Statutory Committee Compliance (Anti-Ragging / ICC-POSH / Grievance Redressal)
    path('statutory-committees/', StatutoryCommitteeViewSet.as_view({'get': 'list', 'post': 'create'}), name='statutorycommittee-list'),
    path('statutory-committees/<int:pk>/', StatutoryCommitteeViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='statutorycommittee-detail'),
    path('committee-memberships/', CommitteeMembershipViewSet.as_view({'get': 'list', 'post': 'create'}), name='committeemembership-list'),
    path('committee-memberships/<int:pk>/', CommitteeMembershipViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='committeemembership-detail'),
    path('committee-complaints/', CommitteeComplaintViewSet.as_view({'get': 'list', 'post': 'create'}), name='committeecomplaint-list'),
    path('committee-complaints/<int:pk>/', CommitteeComplaintViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='committeecomplaint-detail'),
    path('committee-meetings/', CommitteeMeetingViewSet.as_view({'get': 'list', 'post': 'create'}), name='committeemeeting-list'),
    path('committee-meetings/<int:pk>/', CommitteeMeetingViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='committeemeeting-detail'),
    path('compliance-center/reports/statutory-committee-report/', CommitteeAnnualReportView.as_view(), name='compliance-center-statutory-committee'),

    # NAAC SSR/AQAR Evidence Workspace (P6)
    path('accreditation-criteria/', AccreditationCriterionViewSet.as_view({'get': 'list', 'post': 'create'}), name='accreditationcriterion-list'),
    path('accreditation-criteria/<int:pk>/', AccreditationCriterionViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='accreditationcriterion-detail'),
    path('evidence-items/', EvidenceItemViewSet.as_view({'get': 'list', 'post': 'create'}), name='evidenceitem-list'),
    path('evidence-items/<int:pk>/', EvidenceItemViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='evidenceitem-detail'),
    path('evidence-items/<int:pk>/submit/', SubmitEvidenceItemView.as_view(), name='evidenceitem-submit'),
    path('evidence-items/<int:pk>/sign-off/', SignOffEvidenceItemView.as_view(), name='evidenceitem-sign-off'),
    path('compliance-center/ssr-export/', SSRExportView.as_view(), name='compliance-center-ssr-export'),
    path('accreditation-criteria/<int:pk>/narrative-draft/', CriterionNarrativeDraftRequestView.as_view(), name='accreditationcriterion-narrative-draft'),
    path('narrative-drafts/', AccreditationNarrativeDraftViewSet.as_view({'get': 'list'}), name='narrativedraft-list'),
    path('narrative-drafts/<int:pk>/', AccreditationNarrativeDraftViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update'}), name='narrativedraft-detail'),
    path('narrative-drafts/<int:pk>/apply/', NarrativeDraftApplyView.as_view(), name='narrativedraft-apply'),
    path('narrative-drafts/<int:pk>/reject/', NarrativeDraftRejectView.as_view(), name='narrativedraft-reject'),

    # State scholarship reconciliation (missing-module addition)
    path('scholarship-schemes/', StateScholarshipSchemeViewSet.as_view({'get': 'list', 'post': 'create'}), name='scholarshipscheme-list'),
    path('scholarship-schemes/<int:pk>/', StateScholarshipSchemeViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='scholarshipscheme-detail'),
    path('scholarship-records/', StudentScholarshipRecordViewSet.as_view({'get': 'list', 'post': 'create'}), name='scholarshiprecord-list'),
    path('scholarship-records/<int:pk>/', StudentScholarshipRecordViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='scholarshiprecord-detail'),

]

