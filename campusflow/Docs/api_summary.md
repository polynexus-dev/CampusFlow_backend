# CampusFlow API Module & Structure Summary

CampusFlow is a Multi-Tenant SaaS platform for College Management. The backend is designed using Django, Django REST Framework (DRF), and `django-tenants` for schema-based multi-tenancy.

---

## Discovered Modules & Endpoints

A total of **133 URL paths** were discovered across the configuration and application packages. They are grouped into the following functional modules:

### 1. SaaS Management (Public Schema)
*   **Total Endpoints**: 2
*   **Scope**: Django superusers (SaaS Admins) manage tenant provisioning.
*   **Key Operations**: Creating colleges, updating subscription/billing configurations.

### 2. Authentication & Account Verification (Tenant & Public)
*   **Total Endpoints**: 9
*   **Key Operations**: Student self-registration (with email domain validation), staff registration (by College Admin/HOD), email OTP generation and verification, login (JWT pair acquisition), logout (token blacklisting), device binding resets.

### 3. User Profiles & Approval Workflow
*   **Total Endpoints**: 10
*   **Key Operations**: Retrieving personal profile details, viewing HOD/Faculty/Support/Student lists, pending approvals lists, and actioning approvals.

### 4. Academics, Locations & Classrooms
*   **Total Endpoints**: 8
*   **Key Operations**: Department CRUD, campus location definition (coordinates and geofence radius), classroom definition, and validating student coordinate location against classroom entry gates.

### 5. Attendance & Biometric Verification
*   **Total Endpoints**: 16
*   **Key Operations**:
    *   *Lecturer Attendance Session*: Creating session codes, checking status, approving manual requests.
    *   *Student Attendance*: Registering 3-view face embeddings (front, left, right), requesting liveness challenges (eye blink verification), scanning random codes inside geofenced areas, submitting manual logs.

### 6. Leave Management
*   **Total Endpoints**: 7
*   **Key Operations**: Custom leave type CRUD, allocating leave balances, requesting leaves, and head/admin approval actions.

### 7. Payroll & Salary
*   **Total Endpoints**: 5
*   **Key Operations**: User salary structure definition, individual payslip generation, bulk payroll run, and employee payslip search.

### 8. Timetable, Exams & Valuation
*   **Total Endpoints**: 10
*   **Key Operations**: Course definition, lecture schedules, exam types, exam invigilation settings, valuation session allocation, and scanned paper grading.

### 9. Assignments & Submissions
*   **Total Endpoints**: 4
*   **Key Operations**: Assignment definition, student file uploads, grading, and feedback.

### 10. Bus Tracking
*   **Total Endpoints**: 11
*   **Key Operations**: Driver live location routing, route QR code generation, boarding scans, sub-level lists, and stats.

### 11. Fees & Accounts
*   **Total Endpoints**: 8
*   **Key Operations**: Fee category structures, student invoice generation, bulk generation runs, recording payments, and transaction history.

### 12. Other Modules (Others)
*   **Hostel Management** (6 endpoints): Hostel, room, and allocation CRUD.
*   **Library Management** (6 endpoints): Book, barcodes, and checkout/issue CRUD.
*   **Inventory & Store** (8 endpoints): Supplier details, categorizations, items, and transactions.
*   **Training & Placement (TPO)** (4 endpoints): Drive details and placement applications.
