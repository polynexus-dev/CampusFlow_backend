# CampusFlow Authentication & Tenant Routing Workflow

CampusFlow uses standard JSON Web Tokens (JWT) for session management and a custom header/token payload parsing mechanism to route requests to the correct PostgreSQL schema database.

---

## 1. SaaS Onboarding (Tenant Provisioning)
A college must be provisioned by the SaaS Administrator (Django Superuser):

1.  **Endpoint**: `POST /api/saas/create-college/`
2.  **Auth**: Bearer token of a Django superuser.
3.  **Body**:
    ```json
    {
      "name": "MIT College of Engineering",
      "code": "MIT",
      "address": "Pune, Maharashtra",
      "contact_email": "admin@mit.edu.in",
      "permitted_email_domain": "mit.edu.in",
      "domain_name": "mit.localhost",
      "admin_username": "mit_admin",
      "admin_email": "admin@mit.edu.in",
      "admin_password": "SuperSecurePassword123"
    }
    ```
4.  **Action**: The system automatically generates a schema (e.g. `mit_college`), registers `mit.localhost` as a domain, provisions role groups (`student`, `Faculty`, etc.), creates the admin user `mit_admin`, assigns them to the `Management` group, and configures their `ManagementProfile`.

---

## 2. User Self-Registration & Staff Provisioning

### Student Self-Registration (Public)
Students register themselves using the public endpoint. The system routes them to the correct schema database using their email domain.

1.  **Endpoint**: `POST /api/register/student/`
2.  **Header**: `Origin: http://localhost:5173` or `X-Tenant: public`
3.  **Body**:
    ```json
    {
      "username": "student_aniket",
      "email": "aniket@mit.edu.in",
      "password": "SecureStudentPassword123",
      "password2": "SecureStudentPassword123",
      "first_name": "Aniket",
      "last_name": "Kumar",
      "student_id": "STU1001",
      "program_enrolled_in_id": "BTech-CSE",
      "department_id": 1
    }
    ```
4.  **Action**: Since the email domain is `@mit.edu.in`, the middleware automatically routes the request to the `mit_college` schema context. An inactive user is created, and an activation OTP is cached and sent to their email.

### Staff/Faculty Provisioning (Restricted)
College Admins (Management or Administrator) register staff. Self-registration is disabled for staff.

1.  **Endpoint**: `POST /api/register/staff/`
2.  **Auth**: Bearer token of a College Admin.
3.  **Header**: `X-Tenant: mit_college`
4.  **Body**:
    ```json
    {
      "username": "faculty_prof_desai",
      "email": "desai@mit.edu.in",
      "password": "FacultyPassword123",
      "password2": "FacultyPassword123",
      "first_name": "Milind",
      "last_name": "Desai",
      "role": "Faculty", // Or HOD, Support Staff
      "employee_id": "EMP5001",
      "department_id": 1
    }
    ```

---

## 3. Account Verification
Before logging in, self-registered users (and new staff) must verify their email with their OTP:

1.  **Endpoint**: `POST /api/verify-account/`
2.  **Body**:
    ```json
    {
      "email": "aniket@mit.edu.in",
      "otp": "123456"
    }
    ```
3.  **Action**: Activates the user (`is_active = True`).

---

## 4. User Login & Token Storage
1.  **Endpoint**: `POST /api/login/`
2.  **Body**:
    ```json
    {
      "username": "student_aniket",
      "password": "SecureStudentPassword123",
      "device_id": "android_uuid_123456"
    }
    ```
3.  **Response**:
    ```json
    {
      "access": "eyJhbG...",
      "refresh": "eyJhbG...",
      "roleName": "student",
      "tenant_schema": "mit_college",
      "profile": {
        "id": 1,
        "department_id": 1
      }
    }
    ```
4.  **Postman Automations**: The test script automatically stores:
    *   `access_token`
    *   `refresh_token`
    *   `X-Tenant` (stored as `tenant_schema` = `mit_college`)
    *   `student_id` / `user_id`

---

## 5. Token Refreshing
When the access token expires, refresh it without logging in:

1.  **Endpoint**: `POST /api/logout/` (to invalidate or black list) / or standard DRF simplejwt routes.
2.  **Body**:
    ```json
    {
      "refresh": "{{refresh_token}}"
    }
    ```
