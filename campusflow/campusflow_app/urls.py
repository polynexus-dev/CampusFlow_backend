from django.urls import path
from .views.department import DepartmentView, DepartmentDetailView
from .views.users import (
    StudentUserProfileView, VerifyTokenView, StudentRegistrationView, StaffRegistrationView,
    MyObtainTokenPairView, LogoutAPIView, UserProfileView,
    ManagementUserProfileView, AdministratorUserProfileView,
    TeachingStaffUserProfileView, VerifyAccountView, ResendOTPView,
    ResetDeviceLockView, PendingApprovalsView, ApproveUserView
)
from .views.location import LocationDetailView
from .views.attendance import (
    AttendanceMarkView, AllAttendanceView,
    LectureCheckinByCodeView
)
from .views.classroom import ClassroomCreateView, CheckAttendanceView, ClassroomListView, ClassroomLocationValidationView
from .views.lecture import (
    LectureListCreateView, LectureDetailView, LectureByClassroomView,
    GenerateLectureCodeView
)

urlpatterns = [

    # ── Auth ─────────────────────────────────────────────────────────
    path('register/student/', StudentRegistrationView.as_view(), name='student_registration'),
    path('register/staff/', StaffRegistrationView.as_view(), name='staff_registration'),
    path('verify-account/', VerifyAccountView.as_view(), name='verify-account'),
    path('resend-otp/', ResendOTPView.as_view(), name='resend-otp'),
    path('login/', MyObtainTokenPairView.as_view(), name='token_obtain_pair'),
    path('logout/', LogoutAPIView.as_view(), name='logout'),
    path('token/verify/', VerifyTokenView.as_view(), name='verify-token'),
    path('student/reset-device-lock/', ResetDeviceLockView.as_view(), name='reset_device_lock'),

    # ── Approvals ──
    path('approvals/pending/', PendingApprovalsView.as_view(), name='pending_approvals'),
    path('approvals/action/', ApproveUserView.as_view(), name='approve_user_action'),

    # ── Profiles ─────────────────────────────────────────────────────
    # GET own profile (any authenticated user)
    path('user/', UserProfileView.as_view(), name='user_profile'),
    # GET all management profiles (Management / SaaS Admin only)
    path('management/user/', ManagementUserProfileView.as_view(), name='management_user_profile'),
    # GET all administrator profiles (Management / SaaS Admin only)
    path('administrator/user/', AdministratorUserProfileView.as_view(), name='administrator_user_profile'),
    # GET all teaching staff profiles (College Admins / SaaS Admin only)
    path('teaching-staff/user/', TeachingStaffUserProfileView.as_view(), name='teaching_staff_user_profile'),
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
]
