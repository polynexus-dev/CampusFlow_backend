# CampusFlow API — Permissions Reference

> Source of truth: [`permissions.py`](file:///E:/Aniket/next/CampusFlow_backend/campusflow/campusflow_app/permissions.py)

---

## Role Hierarchy (Highest → Lowest)

| Level | Role | Description |
|-------|------|-------------|
| 1 | **SaaS Admin** | Django `is_superuser`. Manages college tenants. Lives in the `public` schema. |
| 2 | **Management** | College's top-level admin (e.g. Principal). Full tenant control. |
| 3 | **Administrator** | College Admin. Can manage all users and settings. |
| 4 | **Department Head (HOD)** | Manages one department. Oversees faculty/students. |
| 5 | **Faculty** | Teaching staff. Manages lectures and attendance for own classes. |
| 6 | **Support Staff** | Non-teaching staff. Cannot mark/create academic records. |
| 7 | **Student** | Most restricted. Can only interact with their own records. |

---

## Permission Class Definitions

| Permission Class | Who can access |
|-----------------|----------------|
| `AllowAny` | Everyone — **no login required** |
| `IsAuthenticated` | Any logged-in user (all roles) |
| `IsNotStudent` | Any role **except** Student |
| `IsFacultyOrAbove` | Faculty, HOD, Administrator, Management, SaaS Admin |
| `IsCollegeAdmin` | Management, Administrator |
| `IsSaaSOrCollegeAdmin` | SaaS Admin, Management, Administrator |
| `IsSaaSAdmin` | SaaS Admin (superuser) only |
| `IsStudent` | Student only |
| `IsFaculty` | Faculty only |
| `CanCreateLecture` | Faculty, HOD, Administrator, Management, SaaS Admin |
| `CanMarkAttendanceManually` | Faculty, HOD, Administrator, Management, SaaS Admin |
| `CanManageLocation` | GET: All authenticated · POST/PATCH/DELETE: College Admin / SaaS Admin |
| `CanGenerateQR` | Faculty, HOD, Administrator, Management, SaaS Admin |

---

## Endpoint Permissions — Full Matrix

### ✅ Public (No Auth Required)

| Method | Endpoint | Notes |
|--------|----------|-------|
| POST | `/api/register/student/` | Self-registration with email domain validation |
| POST | `/api/verify-account/` | OTP email verification |
| POST | `/api/resend-otp/` | Resend registration OTP |
| POST | `/api/login/` | JWT token pair acquisition |

---

### 🔐 Authenticated — Any Logged-in User

| Method | Endpoint | Module | Notes |
|--------|----------|--------|-------|
| GET/PATCH | `/api/user/` | Users | Own profile (role-aware response) |
| GET | `/api/tenant/settings/` | Users | Active tenant info |
| GET | `/api/department/` | Departments | List all departments |
| GET | `/api/department/<id>/` | Departments | Department detail |
| GET | `/api/location/` | Location | List all locations |
| GET | `/api/classrooms/` | Classrooms | List all classrooms |
| GET | `/api/lectures/` | Lectures | List lecture sessions (students filtered to own dept + active code) |
| GET | `/api/lectures/<id>/` | Lectures | Lecture detail |
| GET | `/api/classrooms/<id>/lectures/` | Lectures | Lectures for a specific classroom |
| GET | `/api/courses/` | Courses | List courses |
| GET | `/api/schedules/` | Schedule | Timetable view |
| POST | `/api/logout/` | Auth | Blacklist refresh token |
| GET | `/api/announcements/` | Announcements | All announcements |
| GET | `/api/bus/routes/` | Bus Tracking | List bus routes |
| GET | `/api/bus/summary-stats/` | Bus Tracking | Boarding/route summary statistics |
| GET/POST | `/api/valuation-sessions/` | Valuation | Exam valuation sessions |
| GET/POST | `/api/scanned-papers/` | Valuation | Scanned answer papers |
| GET/POST | `/api/hostels/` | Hostel | Hostel management |
| GET/POST | `/api/hostel-rooms/` | Hostel | Hostel rooms |
| GET/POST | `/api/hostel-allocations/` | Hostel | Room allocations |
| GET/POST | `/api/books/` | Library | Library book catalog |
| GET/POST | `/api/book-issues/` | Library | Book issue records |
| GET/POST | `/api/book-copies/` | Library | Book copy inventory |
| GET/POST | `/api/recruitment-drives/` | TPO | Placement drives |
| GET/POST | `/api/placement-applications/` | TPO | Placement applications |
| GET/POST | `/api/assignments/` | Assignments | Assignment definitions |
| GET/POST | `/api/assignments/<id>/submissions/` | Assignments | Student submissions for an assignment |
| POST | `/api/submissions/<id>/grade/` | Assignments | Grade a submission (Faculty+) |
| GET | `/api/user/allowed-modules/` | Modules | Modules enabled for the caller's role |

---

### 👨‍🎓 Student Only

| Method | Endpoint | Module | Notes |
|--------|----------|--------|-------|
| POST | `/api/register-face/` | Face Attendance | Upload 3-view face photos |
| GET | `/api/liveness-challenge/` | Face Attendance | Request eye-blink challenge |
| POST | `/api/mark-attendance/` | Face Attendance | Submit attendance photo |
| POST | `/api/student/request-biometric-reset/` | Auth | Request to clear face embeddings |
| GET | `/api/student/manual-request-status/` | Attendance | View own manual request status |
| POST | `/api/attendance/lecture-checkin/` | Attendance | Code-based attendance check-in |

---

### 👨‍🏫 Faculty Only

| Method | Endpoint | Module | Notes |
|--------|----------|--------|-------|
| POST | `/api/lecturer/check-in/` | Lecturer Attendance | Start class geofence session |
| POST | `/api/lecturer/start-attendance/` | Lecturer Attendance | Generate random attendance code |
| GET | `/api/lecturer/status/` | Lecturer Attendance | View active session state |
| GET | `/api/lecturer/conducted-history/` | Lecturer Attendance | History of conducted sessions |
| POST | `/api/lecturer/approve-manual-request/` | Lecturer Attendance | Approve/reject manual requests |

---

### 🎓 Faculty or Above

> Faculty, HOD, Administrator, Management, SaaS Admin

| Method | Endpoint | Module | Notes |
|--------|----------|--------|-------|
| POST | `/api/attendance/mark/` | Attendance | Manually mark student attendance |
| GET | `/api/student/user/` | Users | View all student profiles |
| GET | `/api/analytics/attendance-trends/` | Analytics | Cross-lecture attendance analytics |

---

### 🚫 Not Student (Any Staff Role)

> Faculty, HOD, Administrator, Management, Support Staff, SaaS Admin

| Method | Endpoint | Module | Notes |
|--------|----------|--------|-------|
| GET/POST | `/api/leave/types/` | Leave | Leave type definitions |
| POST | `/api/leave/request/` | Leave | Submit leave request |
| GET | `/api/leave/my/` | Leave | View own leave history |
| GET | `/api/leave/balance/` | Leave | View leave balance |
| POST | `/api/leave/action/` | Leave | Approve/reject leave (HOD/Admin) |
| GET | `/api/payroll/payslips/` | Payroll | View own payslips |
| GET | `/api/teaching-staff/user/` | Users | List teaching staff |
| GET | `/api/hod/user/` | Users | List HOD profiles |

---

### 🏛️ College Admin (Management / Administrator)

| Method | Endpoint | Module | Notes |
|--------|----------|--------|-------|
| POST | `/api/register/staff/` | Users | Register Faculty/HOD/Support Staff |
| GET | `/api/approvals/pending/` | Approvals | View pending account approvals |
| POST | `/api/approvals/action/` | Approvals | Approve/reject staff accounts |
| POST/PATCH | `/api/department/` | Departments | Create/update departments |
| POST | `/api/leave/balance/` | Leave | Allocate leave balances |
| GET/POST | `/api/payroll/structures/` | Payroll | Salary structure management |
| POST | `/api/payroll/generate/` | Payroll | Generate payslips |
| POST | `/api/payroll/generate-bulk/` | Payroll | Bulk payroll processing |
| GET/POST | `/api/fees/categories/` | Fees | Fee category management |
| GET/POST | `/api/fees/structures/` | Fees | Fee structure configuration |
| POST | `/api/fees/invoices/bulk-generate/` | Fees | Bulk invoice generation |
| GET/POST | `/api/exams/` | Exams | Exam scheduling |
| GET/POST | `/api/exams/types/` | Exams | Exam type definitions |
| GET | `/api/support-staff/user/` | Users | List support staff profiles |
| POST | `/api/student/reset-device-lock/` | Auth | Reset student device binding |
| POST | `/api/announcements/` | Announcements | Create announcements |

---

### 🔒 SaaS Admin or College Admin

| Method | Endpoint | Module | Notes |
|--------|----------|--------|-------|
| POST/PATCH/DELETE | `/api/location/` | Location | Manage geofenced locations (writes) |
| POST | `/api/classroom/` | Classrooms | Create classrooms |
| GET/POST | `/api/bus/routes/` | Bus Tracking | Manage bus routes |
| GET/POST | `/api/bus/subscriptions/` | Bus Tracking | Manage student bus subscriptions |
| GET/PATCH | `/api/tenant/settings/` | Users | Manage tenant config (writes) |
| GET/POST | `/api/tenant/module-permissions/` | Modules | Configure module toggles |
| GET/POST | `/api/tenant/roles/` | Modules | Configure custom roles |

---

### 🔑 SaaS Admin Only (Superuser)

| Method | Endpoint | Module | Notes |
|--------|----------|--------|-------|
| POST | `/api/saas/create-college/` | SaaS | Provision a new college tenant |
| GET/PATCH | `/api/saas/colleges/<id>/` | SaaS | View/update college config |
| GET/POST | `/api/tenant/subscriptions/<tenant_id>/` | Modules | Manage a tenant's module subscription |

---

## Quick Role Lookup

| Role | Can Access |
|------|-----------|
| **SaaS Admin** | Everything — full platform access |
| **Management** | All college features: payroll, fees, exams, users, leave, bus, announcements |
| **Administrator** | Same as Management within the college |
| **Department Head** | Lecture reports, leave approvals, attendance analytics, own profile |
| **Faculty** | Own lectures, attendance sessions, manual request approvals, assignments |
| **Support Staff** | Leave requests, own payslips, announcements, bus tracking |
| **Student** | Face attendance, code check-in, own profile, announcements, bus |

---

> **Reminder**: All endpoints (except Public) require:
> 1. `Authorization: Bearer {{access_token}}` header
> 2. `X-Tenant: {{tenant_slug}}` header (for all tenant-scoped endpoints)
