# 🚀 CampusFlow ERP — Complete Sequential End-to-End API Testing Manual

> **Purpose:** This document is a complete, copy-paste-ready testing guide for any new developer, tester, or QA engineer. Follow these steps in exact sequential order to test the entire **CampusFlow University ERP** platform from zero to fully configured.
>
> **Target Tenant Under Test:** `CampusNexus Institute of Technology` (`schema: nexus`, domain: `nexus.localhost`)  
> **Server Base URL:** `http://127.0.0.1:8000/api` (or `http://localhost:8000/api`)  
> **Database:** PostgreSQL (Multi-Tenant architecture via `django-tenants`)

---

## 📑 Master Table of Contents
1. [Prerequisites & Postman Environment Setup](#1-prerequisites--postman-environment-setup)
2. [Test User Personas & Credentials](#2-test-user-personas--credentials)
3. [Sequential Step-by-Step API Execution](#3-sequential-step-by-step-api-execution)
   - [Step 1: SaaS Management — Create College Tenant](#step-1-saas-management--create-college-tenant)
   - [Step 2: SaaS Management — Setup Domain Routing](#step-2-saas-management--setup-domain-routing)
   - [Step 3: SaaS SuperAdmin Login](#step-3-saas-superadmin-login)
   - [Step 4: SaaS Management — Assign Subscribed Modules to College](#step-4-saas-management--assign-subscribed-modules-to-college)
   - [Step 5: Onboarding — Register College Admin & Staff](#step-5-onboarding--register-college-admin--staff)
   - [Step 6: Onboarding — Register Student with DPDP Consent](#step-6-onboarding--register-student-with-dpdp-consent)
   - [Step 7: College Admin Login](#step-7-college-admin-login)
   - [Step 8: System Approvals — Approve Faculty Account](#step-8-system-approvals--approve-faculty-account)
   - [Step 9: Faculty & Student Logins](#step-9-faculty--student-logins)
   - [Step 10: Academic Setup — Create Department](#step-10-academic-setup--create-department)
   - [Step 11: Academic Setup — Create Course](#step-11-academic-setup--create-course)
   - [Step 12: Infrastructure — Create Classroom](#step-12-infrastructure--create-classroom)
   - [Step 13: Scheduling — Create Lecture Slot](#step-13-scheduling--create-lecture-slot)
   - [Step 14: Attendance — Faculty Generates Dynamic Check-In Code](#step-14-attendance--faculty-generates-dynamic-check-in-code)
   - [Step 15: Attendance — Student Geofenced Check-In (50m Radius)](#step-15-attendance--student-geofenced-check-in-50m-radius)
   - [Step 16: Attendance — Verify Real-Time Attendance Log](#step-16-attendance--verify-real-time-attendance-log)
   - [Step 17: Assignments — Faculty Publishes Homework](#step-17-assignments--faculty-publishes-homework)
   - [Step 18: Assignments — Student Submits Solution](#step-18-assignments--student-submits-solution)
   - [Step 19: Assignments — Faculty Grades Submission (A+)](#step-19-assignments--faculty-grades-submission-a)
   - [Step 20: Leave Management — Configure Leave Quota](#step-20-leave-management--configure-leave-quota)
   - [Step 21: Leave Management — Faculty Applies for Leave](#step-21-leave-management--faculty-applies-for-leave)
   - [Step 22: Leave Management — Admin Approves Leave Request](#step-22-leave-management--admin-approves-leave-request)
   - [Step 23: Payroll — Setup Faculty Salary Structure](#step-23-payroll--setup-faculty-salary-structure)
   - [Step 24: Payroll — Auto-Generate Monthly Payslip](#step-24-payroll--auto-generate-monthly-payslip)
   - [Step 25: Examinations — Setup Exam Type](#step-25-examinations--setup-exam-type)
   - [Step 26: Examinations — Schedule Mid-Term Exam](#step-26-examinations--schedule-mid-term-exam)
   - [Step 27: Timetable — Setup Recurring Weekly Class Schedule](#step-27-timetable--setup-recurring-weekly-class-schedule)
   - [Step 28: Fees — Create Fee Structure Template](#step-28-fees--create-fee-structure-template)
   - [Step 29: Fees — Generate Student Invoice](#step-29-fees--generate-student-invoice)
   - [Step 30: Fees — Record Fee Payment & Generate Receipt](#step-30-fees--record-fee-payment--generate-receipt)
   - [Step 31: Fees — Inspect Financial Revenue Dashboard](#step-31-fees--inspect-financial-revenue-dashboard)
   - [Step 32: Transit — Create Bus Route & Stops](#step-32-transit--create-bus-route--stops)
   - [Step 33: Transit — Generate Branded Door QR Pass](#step-33-transit--generate-branded-door-qr-pass)
   - [Step 34: Transit — Assign Bus Subscription to Student](#step-34-transit--assign-bus-subscription-to-student)
   - [Step 35: Transit — Student Scans Door QR to Board](#step-35-transit--student-scans-door-qr-to-board)
   - [Step 36: Transit — Driver Starts GPS Trip](#step-36-transit--driver-starts-gps-trip)
   - [Step 37: Announcements — Broadcast Official Notification](#step-37-announcements--broadcast-official-notification)
   - [Step 38: Announcements — Student Views Broadcast](#step-38-announcements--student-views-broadcast)
   - [Step 39: Security Audit — Inspect Institutional Audit Trail](#step-39-security-audit--inspect-institutional-audit-trail)
   - [Step 40: Analytics — Get Executive Overview Dashboard](#step-40-analytics--get-executive-overview-dashboard)
   - [Step 41: Settings — Update Tenant Customizations & Timezone](#step-41-settings--update-tenant-customizations--timezone)
   - [Step 42: Profiles — Update Self Profile](#step-42-profiles--update-self-profile)
   - [Step 43: Lecturer Controls — Faculty Room Check-In](#step-43-lecturer-controls--faculty-room-check-in)
   - [Step 44: Lecturer Controls — Start 3-Minute Attendance Window](#step-44-lecturer-controls--start-3-minute-attendance-window)
   - [Step 45: Lecturer Controls — Approve Student Manual Attendance Request](#step-45-lecturer-controls--approve-student-manual-attendance-request)
   - [Step 46: Role Permissions — Configure Module Permissions](#step-46-role-permissions--configure-module-permissions)
   - [Step 47: Role Permissions — Create Custom Role](#step-47-role-permissions--create-custom-role)
   - [Step 48: Hostels — Create Student Hostel](#step-48-hostels--create-student-hostel)
   - [Step 49: Hostels — Create Hostel Room](#step-49-hostels--create-hostel-room)
   - [Step 50: Hostels — Allocate Student to Hostel Room](#step-50-hostels--allocate-student-to-hostel-room)
   - [Step 51: Inventory — Create Inventory Category](#step-51-inventory--create-inventory-category)
   - [Step 52: Inventory — Add Stock Item](#step-52-inventory--add-stock-item)
   - [Step 53: Inventory — Register Supplier](#step-53-inventory--register-supplier)
   - [Step 54: Inventory — Record Department Issue Transaction](#step-54-inventory--record-department-issue-transaction)
   - [Step 55: Library — Add Book to Catalog](#step-55-library--add-book-to-catalog)
   - [Step 56: Library — Register Physical Barcoded Copy](#step-56-library--register-physical-barcoded-copy)
   - [Step 57: Library — Issue Book to Student](#step-57-library--issue-book-to-student)
   - [Step 58: Placements — Publish Campus Recruitment Drive](#step-58-placements--publish-campus-recruitment-drive)
   - [Step 59: Placements — Student Applies for Job Drive](#step-59-placements--student-applies-for-job-drive)
   - [Step 60: Placements — Officer Selects Candidate & Records CTC](#step-60-placements--officer-selects-candidate--records-ctc)
   - [Step 61: Valuation — Start Digital Valuation Session](#step-61-valuation--start-digital-valuation-session)
   - [Step 62: Valuation — Ingest Scanned Answer Sheet](#step-62-valuation--ingest-scanned-answer-sheet)
   - [Step 63: Valuation — Faculty Evaluates & Marks Paper](#step-63-valuation--faculty-evaluates--marks-paper)
   - [Step 64: DPDP Compliance — Submit Right-to-be-Forgotten Request](#step-64-dpdp-compliance--submit-right-to-be-forgotten-request)
   - [Step 65: College Administration — Assign Direct Permissions to Staff](#step-65-college-administration--assign-direct-permissions-to-staff)

---

## 1. Prerequisites & Postman Environment Setup

### Environment Variables
In Postman, create an Environment named **`Local_Backend`** with the following variables:
* `baseUrl`: `http://127.0.0.1:8000/api`
* `schema`: `nexus`
* `jwtToken`: *(Populated dynamically on login)*
* `saasAdminToken`: *(Populated on superadmin login)*

### Global Multi-Tenant Headers Rule
* For **SaaS Platform / Superadmin** requests: Pass header `X-Tenant: public` (or `X-Tenant-Schema: public`).
* For **College Tenant (`nexus`)** requests: Pass header `X-Tenant-Schema: nexus` (or `X-Tenant: nexus`).

---

## 2. Test User Personas & Credentials

| Role | Username | Email | Password | Persona & Scope |
| :--- | :--- | :--- | :--- | :--- |
| 👑 **SaaS SuperAdmin** | `admin` | `admin@polynexus.com` | `admin` | Cloud SaaS Owner (`public` schema) |
| 🏛️ **College Admin** | `admin_nexus` | `admin@campusnexus.in` | `Admin@123` | Institutional Head of `nexus` college |
| 👨‍🏫 **Faculty Member** | `prof_sharma` | `sharma@campusnexus.in` | `Password123!` | CS Professor (Lectures, Grading, Exams) |
| 🎒 **Student** | `student_rahul` | `rahul@nexus.edu` | `Password123!` | Enrolled B.Tech Student |

---

## 3. Sequential Step-by-Step API Execution

---

### Step 1: SaaS Management — Create College Tenant
* **Actor:** SaaS SuperAdmin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/saas/tenants/`
* **Headers:**
  ```http
  Authorization: Bearer {{saasAdminToken}}
  X-Tenant: public
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "name": "CampusNexus Institute of Technology",
    "schema_name": "nexus",
    "permitted_email_domain": "campusnexus.in"
  }
  ```
* **Expected Response (`201 Created`):**
  ```json
  {
    "id": 2,
    "name": "CampusNexus Institute of Technology",
    "schema_name": "nexus"
  }
  ```

---

### Step 2: SaaS Management — Setup Domain Routing
* **Actor:** SaaS SuperAdmin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/saas/domains/`
* **Headers:**
  ```http
  Authorization: Bearer {{saasAdminToken}}
  X-Tenant: public
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "domain": "nexus.localhost",
    "tenant": 2,
    "is_primary": true
  }
  ```
* **Expected Response (`201 Created`):**
  ```json
  {
    "id": 1,
    "domain": "nexus.localhost",
    "tenant": 2
  }
  ```

---

### Step 3: SaaS SuperAdmin Login
* **Method:** `POST`
* **URL:** `{{baseUrl}}/login/`
* **Headers:**
  ```http
  X-Tenant: public
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "username": "admin",
    "password": "admin"
  }
  ```
* **Action:** Copy `"access"` token into `{{saasAdminToken}}`.

---

### Step 4: SaaS Management — Assign Subscribed Modules to College
* **Actor:** SaaS SuperAdmin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/tenant/subscriptions/2/`
* **Headers:**
  ```http
  Authorization: Bearer {{saasAdminToken}}
  X-Tenant: public
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "subscribed_modules": [
      "attendance", "schedule", "leave", "payroll", "exams", "assignments",
      "fees", "bus-tracking", "hostel", "tpo", "library", "inventory",
      "valuation", "analytics", "announcements"
    ]
  }
  ```

---

### Step 5: Onboarding — Register College Admin & Staff
* **Method:** `POST`
* **URL:** `{{baseUrl}}/register/staff/`
* **Headers:**
  ```http
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "username": "prof_sharma",
    "email": "sharma@campusnexus.in",
    "password": "Password123!",
    "password2": "Password123!",
    "role": "Faculty",
    "employee_id": "EMP-CSE-001",
    "first_name": "Rakesh",
    "last_name": "Sharma",
    "consent_given": true
  }
  ```

---

### Step 6: Onboarding — Register Student with DPDP Consent
* **Method:** `POST`
* **URL:** `{{baseUrl}}/register/student/`
* **Headers:**
  ```http
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "username": "student_rahul",
    "email": "rahul@nexus.edu",
    "password": "Password123!",
    "password2": "Password123!",
    "student_id": "STU2026-001",
    "first_name": "Rahul",
    "last_name": "Verma",
    "contact_number": "+91 9876543210",
    "consent_given": true
  }
  ```

---

### Step 7: College Admin Login
* **Method:** `POST`
* **URL:** `{{baseUrl}}/login/`
* **Headers:**
  ```http
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "username": "admin_nexus",
    "password": "Admin@123"
  }
  ```
* **Action:** Copy `"access"` token into `{{jwtToken}}` (or use for admin requests).

---

### Step 8: System Approvals — Approve Faculty Account
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/approvals/action/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "user_id": 2,
    "action": "approve"
  }
  ```

---

### Step 9: Faculty & Student Logins
Log in as **`prof_sharma`** (Password: `Password123!`) and **`student_rahul`** (Password: `Password123!`) via `POST {{baseUrl}}/login/` with header `X-Tenant-Schema: nexus` to obtain active tokens.

---

### Step 10: Academic Setup — Create Department
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/department/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "name": "Computer Science & Engineering",
    "code": "CSE",
    "description": "Department of CS & IT Engineering"
  }
  ```

---

### Step 11: Academic Setup — Create Course
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/courses/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "course_name": "Data Structures & Algorithms",
    "course_code": "CS101",
    "department": 1,
    "credits": 4,
    "semester": "3"
  }
  ```

---

### Step 12: Infrastructure — Create Classroom
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/classroom/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "name": "Room 101 - CS Lab",
    "code": "LH-101",
    "capacity": 60
  }
  ```

---

### Step 13: Scheduling — Create Lecture Slot
* **Actor:** Faculty / Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/lectures/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_OR_FACULTY_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "name": "Data Structures Lecture 1",
    "subject": "Data Structures & Algorithms",
    "classroom": 1,
    "faculty": 2,
    "start_time": "2026-10-01T09:00:00Z",
    "end_time": "2026-10-01T10:30:00Z"
  }
  ```

---

### Step 14: Attendance — Faculty Generates Dynamic Check-In Code
* **Actor:** Prof. Sharma
* **Method:** `POST`
* **URL:** `{{baseUrl}}/lectures/1/generate-code/`
* **Headers:**
  ```http
  Authorization: Bearer <PROF_SHARMA_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "latitude": 18.5204,
    "longitude": 73.8567
  }
  ```
* **Expected Response (`200 OK`):** Returns 6-character code (e.g. `"code": "AB12CD"`).

---

### Step 15: Attendance — Student Geofenced Check-In (50m Radius)
* **Actor:** Student Rahul
* **Method:** `POST`
* **URL:** `{{baseUrl}}/attendance/checkin-by-code/`
* **Headers:**
  ```http
  Authorization: Bearer <STUDENT_RAHUL_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "code": "AB12CD",
    "latitude": 18.52041,
    "longitude": 73.85671,
    "device_id": "device_rahul_mobile_01"
  }
  ```

---

### Step 16: Attendance — Verify Real-Time Attendance Log
* **Method:** `GET`
* **URL:** `{{baseUrl}}/attendance/all/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_OR_FACULTY_TOKEN>
  X-Tenant-Schema: nexus
  ```

---

### Step 17: Assignments — Faculty Publishes Homework
* **Actor:** Prof. Sharma
* **Method:** `POST`
* **URL:** `{{baseUrl}}/assignments/`
* **Headers:**
  ```http
  Authorization: Bearer <PROF_SHARMA_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "title": "Assignment 1: Binary Search Trees",
    "description": "Implement an AVL tree with insertion, deletion, and rotation algorithms in Python.",
    "course": 1,
    "due_date": "2026-10-15T23:59:59Z",
    "max_marks": 50
  }
  ```

---

### Step 18: Assignments — Student Submits Solution
* **Actor:** Student Rahul
* **Method:** `POST`
* **URL:** `{{baseUrl}}/assignments/1/submissions/`
* **Headers:**
  ```http
  Authorization: Bearer <STUDENT_RAHUL_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "text_submission": "class Node:\n    def __init__(self, key):\n        self.key = key\n        self.left = None\n        self.right = None\n        self.height = 1"
  }
  ```

---

### Step 19: Assignments — Faculty Grades Submission (A+)
* **Actor:** Prof. Sharma
* **Method:** `POST`
* **URL:** `{{baseUrl}}/submissions/1/grade/`
* **Headers:**
  ```http
  Authorization: Bearer <PROF_SHARMA_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "marks_obtained": 48.5,
    "grade": "A+",
    "feedback": "Flawless AVL rebalancing and tree traversal implementation."
  }
  ```

---

### Step 20: Leave Management — Configure Leave Quota
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/leave/types/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "name": "Casual Leave",
    "code": "CL",
    "days_allowed_per_year": 12,
    "is_paid": true
  }
  ```

---

### Step 21: Leave Management — Faculty Applies for Leave
* **Actor:** Prof. Sharma
* **Method:** `POST`
* **URL:** `{{baseUrl}}/leave/request/`
* **Headers:**
  ```http
  Authorization: Bearer <PROF_SHARMA_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "leave_type": 1,
    "start_date": "2026-10-10",
    "end_date": "2026-10-12",
    "reason": "Attending IEEE International Computer Vision Conference"
  }
  ```

---

### Step 22: Leave Management — Admin Approves Leave Request
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/leave/action/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "request_id": 1,
    "action": "approve"
  }
  ```

---

### Step 23: Payroll — Setup Faculty Salary Structure
* **Actor:** College Admin
* **Method:** `PUT`
* **URL:** `{{baseUrl}}/payroll/structures/2/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "basic_pay": "50000.00",
    "hra": "15000.00",
    "da": "10000.00",
    "ta": "7000.00",
    "pf_deduction": "6000.00",
    "tax_deduction": "4000.00"
  }
  ```

---

### Step 24: Payroll — Auto-Generate Monthly Payslip
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/payroll/payslips/generate/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "employee_id": 2,
    "month": 10,
    "year": 2026
  }
  ```

---

### Step 25: Examinations — Setup Exam Type
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/exams/types/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "name": "Mid-Term Examination",
    "code": "MID"
  }
  ```

---

### Step 26: Examinations — Schedule Mid-Term Exam
* **Actor:** College Admin / Faculty
* **Method:** `POST`
* **URL:** `{{baseUrl}}/exams/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "name": "Data Structures Mid-Term Exam",
    "exam_type": 1,
    "course": 1,
    "classroom": 1,
    "date": "2026-10-25",
    "start_time": "09:30:00",
    "end_time": "11:30:00",
    "total_marks": "50.00",
    "passing_marks": "18.00"
  }
  ```

---

### Step 27: Timetable — Setup Recurring Weekly Class Schedule
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/schedules/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "course": 1,
    "classroom": 1,
    "faculty": 2,
    "day_of_week": "Monday",
    "start_time": "09:00:00",
    "end_time": "10:30:00"
  }
  ```

---

### Step 28: Fees — Create Fee Structure Template
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/fees/structures/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "name": "B.Tech CSE Semester 1",
    "department": 1,
    "academic_year": "2026-2027",
    "total_amount": "45000.00"
  }
  ```

---

### Step 29: Fees — Generate Student Invoice
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/fees/invoices/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "student": 1,
    "fee_structure": 1,
    "due_date": "2026-11-30",
    "total_amount": "45000.00"
  }
  ```

---

### Step 30: Fees — Record Fee Payment & Generate Receipt
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/fees/invoices/1/pay/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "amount": "45000.00",
    "payment_mode": "UPI",
    "transaction_reference": "UPI/20261001/8877665544"
  }
  ```

---

### Step 31: Fees — Inspect Financial Revenue Dashboard
* **Method:** `GET`
* **URL:** `{{baseUrl}}/fees/dashboard/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  ```

---

### Step 32: Transit — Create Bus Route & Stops
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/bus/routes/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "name": "Route 1 - City Center to Campus",
    "stops_data": [
      {"name": "City Center Stop", "latitude": 18.5204, "longitude": 73.8567, "sequence": 1},
      {"name": "Tech Park Junction", "latitude": 18.5300, "longitude": 73.8600, "sequence": 2},
      {"name": "Campus Main Gate", "latitude": 18.5400, "longitude": 73.8700, "sequence": 3}
    ]
  }
  ```

---

### Step 33: Transit — Generate Branded Door QR Pass
* **Method:** `GET`
* **URL:** `{{baseUrl}}/bus/routes/1/qr/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  ```
* **Expected Response:** Generates branded PNG pass with `new_qr_token`.

---

### Step 34: Transit — Assign Bus Subscription to Student
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/bus/subscriptions/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "student": 1,
    "route": 1,
    "valid_until": "2027-06-30",
    "status": "Active"
  }
  ```

---

### Step 35: Transit — Student Scans Door QR to Board
* **Actor:** Student Rahul
* **Method:** `POST`
* **URL:** `{{baseUrl}}/bus/scan/`
* **Headers:**
  ```http
  Authorization: Bearer <STUDENT_RAHUL_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "qr_token": "<QR_TOKEN_FROM_STEP_33>"
  }
  ```

---

### Step 36: Transit — Driver Starts GPS Trip
* **Method:** `POST`
* **URL:** `{{baseUrl}}/bus/driver/trip/start/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_OR_DRIVER_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "route_id": 1,
    "latitude": 18.5204,
    "longitude": 73.8567
  }
  ```

---

### Step 37: Announcements — Broadcast Official Notification
* **Actor:** College Admin / Faculty
* **Method:** `POST`
* **URL:** `{{baseUrl}}/announcements/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_OR_FACULTY_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "title": "Mid-Term Examination Schedule Released",
    "content": "All B.Tech CSE students are requested to review their timetable for the Data Structures Mid-Term Exam.",
    "priority": "high",
    "target_roles": ["student", "Faculty"],
    "is_pinned": true
  }
  ```

---

### Step 38: Announcements — Student Views Broadcast
* **Actor:** Student Rahul
* **Method:** `GET`
* **URL:** `{{baseUrl}}/announcements/`
* **Headers:**
  ```http
  Authorization: Bearer <STUDENT_RAHUL_TOKEN>
  X-Tenant-Schema: nexus
  ```

---

### Step 39: Security Audit — Inspect Institutional Audit Trail
* **Actor:** College Admin
* **Method:** `GET`
* **URL:** `{{baseUrl}}/audit-logs/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  ```

---

### Step 40: Analytics — Get Executive Overview Dashboard
* **Actor:** College Admin
* **Method:** `GET`
* **URL:** `{{baseUrl}}/analytics/overview/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  ```

---

### Step 41: Settings — Update Tenant Customizations & Timezone
* **Actor:** College Admin
* **Method:** `PATCH`
* **URL:** `{{baseUrl}}/tenant/settings/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "name": "CampusNexus Institute of Technology & Research",
    "timezone": "Asia/Kolkata"
  }
  ```

---

### Step 42: Profiles — Update Self Profile
* **Actor:** Any Authenticated User
* **Method:** `PUT`
* **URL:** `{{baseUrl}}/user/`
* **Headers:**
  ```http
  Authorization: Bearer <USER_JWT_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "contact_number": "+91 9876543210",
    "user": {
      "first_name": "Rahul",
      "last_name": "Verma"
    }
  }
  ```

---

### Step 43: Lecturer Controls — Faculty Room Check-In
* **Actor:** Prof. Sharma
* **Method:** `POST`
* **URL:** `{{baseUrl}}/lecturer/check-in/`
* **Headers:**
  ```http
  Authorization: Bearer <PROF_SHARMA_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "lecture_id": 1,
    "latitude": 18.5204,
    "longitude": 73.8567
  }
  ```

---

### Step 44: Lecturer Controls — Start 3-Minute Attendance Window
* **Actor:** Prof. Sharma
* **Method:** `POST`
* **URL:** `{{baseUrl}}/lecturer/start-attendance/`
* **Headers:**
  ```http
  Authorization: Bearer <PROF_SHARMA_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "lecture_id": 1
  }
  ```

---

### Step 45: Lecturer Controls — Approve Student Manual Attendance Request
* **Actor:** Prof. Sharma
* **Method:** `POST`
* **URL:** `{{baseUrl}}/lecturer/approve-manual-request/`
* **Headers:**
  ```http
  Authorization: Bearer <PROF_SHARMA_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "request_id": 1,
    "action": "approve"
  }
  ```

---

### Step 46: Role Permissions — Configure Module Permissions
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/tenant/module-permissions/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "group_name": "Faculty",
    "allowed_modules": [
      "attendance", "schedule", "assignments", "exams", "leave", "announcements"
    ]
  }
  ```

---

### Step 47: Role Permissions — Create Custom Role
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/tenant/roles/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "role_name": "Lab Assistant"
  }
  ```

---

### Step 48: Hostels — Create Student Hostel
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/hostels/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "name": "Sahyadri Boys Hostel",
    "gender_type": "Boys",
    "capacity": 200,
    "address": "North Campus, Gate 2"
  }
  ```

---

### Step 49: Hostels — Create Hostel Room
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/hostel-rooms/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "hostel": 1,
    "room_number": "101",
    "capacity": 2,
    "rent_per_semester": "25000.00"
  }
  ```

---

### Step 50: Hostels — Allocate Student to Hostel Room
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/hostel-allocations/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "student": 1,
    "room": 1,
    "status": "Allocated"
  }
  ```

---

### Step 51: Inventory — Create Inventory Category
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/inventory-categories/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "name": "Lab Electronics & Hardware",
    "description": "Microcontrollers, Sensors, Raspberry Pis, and Lab Cables"
  }
  ```

---

### Step 52: Inventory — Add Stock Item
* **Actor:** College Admin / Store Keeper
* **Method:** `POST`
* **URL:** `{{baseUrl}}/inventory-items/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "category": 1,
    "name": "Arduino Uno R3 Starter Kit",
    "quantity": 50,
    "unit": "boxes",
    "threshold_level": 10
  }
  ```

---

### Step 53: Inventory — Register Supplier
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/suppliers/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "name": "TechFab Electronics Supply Pvt Ltd",
    "contact_person": "Ramesh Gupta",
    "phone": "+91 9820011223",
    "email": "orders@techfab.in",
    "address": "Electronic City, Phase 1, Bangalore"
  }
  ```

---

### Step 54: Inventory — Record Department Issue Transaction
* **Actor:** Store Keeper / Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/inventory-transactions/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "item": 1,
    "transaction_type": "Issue",
    "quantity": 5,
    "department": 1,
    "remarks": "Issued for CS101 Embedded Systems Workshop"
  }
  ```

---

### Step 55: Library — Add Book to Catalog
* **Actor:** Librarian / Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/books/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "title": "Introduction to Algorithms (4th Edition)",
    "author": "Thomas H. Cormen, Charles E. Leiserson",
    "isbn": "978-0262046305",
    "publisher": "MIT Press",
    "total_copies": 5,
    "available_copies": 5
  }
  ```

---

### Step 56: Library — Register Physical Barcoded Copy
* **Actor:** Librarian
* **Method:** `POST`
* **URL:** `{{baseUrl}}/book-copies/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "book": 1,
    "barcode": "LIB-CS-2026-001",
    "status": "Available"
  }
  ```

---

### Step 57: Library — Issue Book to Student
* **Actor:** Librarian
* **Method:** `POST`
* **URL:** `{{baseUrl}}/book-issues/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "book_copy": 1,
    "student": 1,
    "due_date": "2026-10-30",
    "status": "Issued"
  }
  ```

---

### Step 58: Placements — Publish Campus Recruitment Drive
* **Actor:** Placement Officer / Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/recruitment-drives/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "company_name": "Google India",
    "job_title": "Associate Software Engineer",
    "job_description": "Full-stack development, Python, Distributed Systems",
    "eligibility_criteria": "B.Tech CSE / IT with minimum 7.5 CGPA and no backlogs",
    "package_lpa": "24.50",
    "drive_date": "2026-11-15",
    "status": "Active"
  }
  ```

---

### Step 59: Placements — Student Applies for Job Drive
* **Actor:** Student Rahul
* **Method:** `POST`
* **URL:** `{{baseUrl}}/placement-applications/`
* **Headers:**
  ```http
  Authorization: Bearer <STUDENT_RAHUL_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "drive": 1,
    "status": "Applied",
    "remarks": "Submitted resume and portfolio link"
  }
  ```

---

### Step 60: Placements — Officer Selects Candidate & Records CTC
* **Actor:** Placement Officer
* **Method:** `PATCH`
* **URL:** `{{baseUrl}}/placement-applications/1/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "status": "Selected",
    "offered_ctc_lpa": "24.50",
    "remarks": "Selected in campus hiring drive"
  }
  ```

---

### Step 61: Valuation — Start Digital Valuation Session
* **Actor:** Exam Cell / Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/valuation-sessions/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "exam": 1,
    "evaluator": 1,
    "status": "Active"
  }
  ```

---

### Step 62: Valuation — Ingest Scanned Answer Sheet
* **Actor:** Exam Cell / Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/scanned-papers/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "session": 1,
    "student": 1,
    "status": "Pending",
    "scanned_file_url": "https://storage.campusnexus.in/scans/2026/cs101_midterm_stu001.pdf"
  }
  ```

---

### Step 63: Valuation — Faculty Evaluates & Marks Paper
* **Actor:** Prof. Sharma (Evaluator)
* **Method:** `PATCH`
* **URL:** `{{baseUrl}}/scanned-papers/1/`
* **Headers:**
  ```http
  Authorization: Bearer <PROF_SHARMA_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "allocated_marks": "46.50",
    "question_scores": {
      "Q1": 18.0,
      "Q2": 15.0,
      "Q3": 13.5
    },
    "status": "Evaluated",
    "remarks": "Excellent AVL tree balancing implementation."
  }
  ```

---

### Step 64: DPDP Compliance — Submit Right-to-be-Forgotten Request
* **Actor:** Student Rahul
* **Method:** `POST`
* **URL:** `{{baseUrl}}/user/request-erasure/`
* **Headers:**
  ```http
  Authorization: Bearer <STUDENT_RAHUL_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "reason": "Graduating student requesting purge of optional telemetry data."
  }
  ```

---

### Step 65: College Administration — Assign Direct Permissions to Staff
* **Actor:** College Admin
* **Method:** `POST`
* **URL:** `{{baseUrl}}/college/user-permissions/2/`
* **Headers:**
  ```http
  Authorization: Bearer <ADMIN_NEXUS_TOKEN>
  X-Tenant-Schema: nexus
  Content-Type: application/json
  ```
* **Payload:**
  ```json
  {
    "permissions": [
      "add_lecture",
      "change_lecture",
      "add_attendance",
      "change_attendance",
      "add_assignment",
      "change_assignment"
    ]
  }
  ```

---

## 4. Verification Summary

By completing all 65 sequential steps above:
* ✅ 1 College Tenant (`nexus`) is provisioned in complete database isolation.
* ✅ 4 Real-world personas (Superadmin, College Admin, Teacher, Student) are registered, vetted, and active.
* ✅ All academic, administrative, financial, transit, residential, and library modules have been populated with live records.
* ✅ Anti-proxy attendance, homework grading, automated payroll, UPI fees, bus QR scans, and digital answer paper valuation are 100% verified.

---
> *Testing Guide Prepared for CampusFlow Enterprise Engineering & QA Teams.*  
> *Target System: CampusFlow Backend v5.0 | All 65 Steps Ready for Execution.*
