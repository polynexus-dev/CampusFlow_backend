from django.urls import path
from tenants.views import InvoiceListAPIView, InvoiceUploadReceiptAPIView
from .views.department import DepartmentView, DepartmentDetailView
from .views.users import (
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
from .views.location import LocationDetailView
from .views.attendance import (
    AttendanceMarkView, AllAttendanceView,
    LectureCheckinByCodeView
)
from .views.face_attendance import (
    FaceRegistrationView, LivenessChallengeView,
    MarkAttendanceView, AttendanceHistoryView,
    StudentRequestManualAttendanceView, StudentManualRequestStatusView
)
from .views.lecturer_attendance import (
    LecturerCheckInView, LecturerStartSessionView,
    LecturerAttendanceStatusView, LecturerManualRequestsView,
    LecturerApproveManualRequestView, LecturerConductedHistoryView,
    LecturerBulkApproveManualRequestsView, LecturerDeviceResetRequestsView,
    LecturerApproveDeviceResetRequestView
)
from .views.classroom import ClassroomCreateView, CheckAttendanceView, ClassroomListView, ClassroomLocationValidationView
from .views.lecture import (
    LectureListCreateView, LectureDetailView, LectureByClassroomView,
    GenerateLectureCodeView
)

# ── New Module Imports ──
from .views.audit import AuditLogListView
from .views.announcement import AnnouncementListCreateView, AnnouncementDetailView
from .views.leave import (
    LeaveTypeListCreateView, LeaveTypeDetailView,
    LeaveBalanceView, LeaveRequestCreateView, LeaveRequestListView,
    LeaveRequestActionView, MyLeavesView
)
from .views.payroll import (
    SalaryStructureListView, SalaryStructureDetailView,
    GeneratePayslipView, BulkPayslipGenerationView, PayslipListView
)
from .views.exam import ExamTypeListCreateView, ExamListCreateView, ExamDetailView
from .views.course import CourseListCreateView
from .views.schedule import ScheduleListView, TeacherTodayScheduleView
from .views.attendance_correction import (
    GuardianCreateCorrectionRequestView, TeacherCorrectionRequestListView,
    TeacherCorrectionRequestActionView,
)
from .views.quick_create import QuickCreatePostView
from .views.enrollment import AdminEnrollStudentView, StudentConsentGrantView, EnrollmentStatsView
from .views.face_registration_queue import (
    FaceRegistrationQueueView, FaceRegistrationCaptureView, FaceRegistrationRetakeView,
)
from .views.promotion import PromoteClassView, PromoteClassRevertView
from .views.parent_link_request import (
    ParentLinkRequestCreateView, AdminParentLinkRequestListView, AdminParentLinkRequestActionView,
)
from .views.question_bank import (
    SyllabusTopicListCreateView, SyllabusTopicDetailView,
    QuestionBankListCreateView, QuestionDetailView,
)
from .views.paper_setting import (
    PaperBlueprintView, GeneratePaperView, ExamPaperView,
    ExamQuestionAddView, ExamQuestionReplaceView, ExamQuestionDetailView,
    FinalizePaperView,
)
from .views.assignment import AssignmentListCreateView, AssignmentDetailView
from .views.submission import SubmissionListCreateView, SubmissionGradeView
from .views.analytics import (
    OverviewKPIView, AttendanceTrendsView, DepartmentPerformanceView,
    LeaveAnalyticsView, PayrollSummaryView
)
from .views.bus_tracking import (
    BusRouteListCreateView, BusRouteDetailView,
    BusRouteQRView, BusRouteRegenQRView,
    BusLiveLocationsView, BusTrailView,
    BusSubscriptionListCreateView, BusSubscriptionDetailView,
    BusBoardingScanView, BusAttendanceListView,
    BusDriverDashboardView, BusSummaryStatsView,
    BusTripStartView, BusTripEndView, BusDriverTripStatsView,
    BusConductorScanStudentView, BusTripSummaryView, StudentIDQRView,
)
from .views.notifications import (
    NotificationListView, NotificationMarkReadView, NotificationUnreadCountView,
)
from .views.fees import (
    FeeCategoryViewSet, FeeStructureViewSet, StudentFeeInvoiceViewSet,
    BulkGenerateInvoicesView, RecordFeePaymentView, FeePaymentListView,
    FeeDashboardView
)
from .views.payments import (
    CreatePaymentOrderView, VerifyPaymentView, RazorpayWebhookView
)
from .views.module_permissions import (
    TenantSubscriptionView, RoleModulePermissionView, MyAllowedModulesView, CustomRolesView
)
from .views.hostel import HostelViewSet, HostelRoomViewSet, HostelAllocationViewSet
from .views.tpo import RecruitmentDriveViewSet, PlacementApplicationViewSet
from .views.library import BookViewSet, BookCopyViewSet, BookIssueViewSet
from .views.inventory import InventoryCategoryViewSet, InventoryItemViewSet, SupplierViewSet, InventoryTransactionViewSet
from .views.valuation import ValuationSessionViewSet, ScannedPaperViewSet
from .views.result import StudentExamResultViewSet, ExamClassStatsView, ExamPublishResultsView
from .views.result_correction import (
    ResultCorrectionRequestCreateView, HMCorrectionRequestListView, HMCorrectionRequestActionView,
)
from .views.progress import StudentProgressView, StudentTopicPerformanceView
from .views.contact import ContactEnquiryView
from .views.guardian import (
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
    path('schedules/', ScheduleListView.as_view(), name='schedule-list'),
    path('schedule/today/', TeacherTodayScheduleView.as_view(), name='schedule-today'),

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

    # ── Paper Setting from Syllabus ───────────────────────────────────
    path('exams/<int:pk>/blueprint/', PaperBlueprintView.as_view(), name='exam-paper-blueprint'),
    path('exams/<int:pk>/paper/generate/', GeneratePaperView.as_view(), name='exam-paper-generate'),
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

    # Student Exam Results
    path('exam-results/', StudentExamResultViewSet.as_view({'get': 'list', 'post': 'create'}), name='studentexamresult-list'),
    path('exam-results/<int:pk>/', StudentExamResultViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='studentexamresult-detail'),
    path('exams/<int:pk>/class-stats/', ExamClassStatsView.as_view(), name='exam-class-stats'),
    path('exams/<int:pk>/publish-results/', ExamPublishResultsView.as_view(), name='exam-publish-results'),
    path('results/corrections/', ResultCorrectionRequestCreateView.as_view(), name='result-correction-create'),
    path('results/corrections/list/', HMCorrectionRequestListView.as_view(), name='result-correction-list'),
    path('results/corrections/<int:pk>/action/', HMCorrectionRequestActionView.as_view(), name='result-correction-action'),

    # ── Parent / Guardian Endpoints ──
    path('parent/children/', ParentChildrenListView.as_view(), name='parent-children-list'),
    path('parent/children/link/', ParentLinkChildView.as_view(), name='parent-link-child'),
    path('parent/children/<int:student_id>/attendance/', ParentChildAttendanceView.as_view(), name='parent-child-attendance'),
    path('parent/children/<int:student_id>/fees/', ParentChildFeesView.as_view(), name='parent-child-fees'),
    path('parent/children/<int:student_id>/exams/', ParentChildExamsView.as_view(), name='parent-child-exams'),
    path('parent/children/<int:student_id>/assignments/', ParentChildAssignmentsView.as_view(), name='parent-child-assignments'),

]

