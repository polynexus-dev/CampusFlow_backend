"""
Dynamic Client Legal Agreement Generator for CampusNexus.

Generates a printable, PDF-ready HTML Master Client Agreement populated with a
specific Tenant's details, subscribed modules, billing rates, and payment
gateway settings. Restricted strictly to the SaaS Owner (superuser).
"""
from decimal import Decimal
import html
from django.utils import timezone
from django_tenants.utils import schema_context


MODULE_CATALOG = [
    ("management", "Management Portal & Core Academics"),
    ("administrator", "Administrator Console & RBAC"),
    ("department", "Department & Curriculum Administration"),
    ("room", "Classroom & Geofence Room Manager"),
    ("staff", "Staff & Faculty Directory"),
    ("student", "Student Console & Lifecycle"),
    ("attendance", "Attendance (Biometric Face & Geo-Fence)"),
    ("schedule", "Automated Timetable & Schedule"),
    ("leave", "HR & Leave Management"),
    ("payroll", "Staff Payroll & Payslip Generation"),
    ("exams", "Examinations, Grading & Transcripts"),
    ("valuation", "Digital Answer Script Valuation"),
    ("assignments", "Course Assignments & Submissions"),
    ("fees", "Student Fee Invoicing & Online Payments"),
    ("bus-tracking", "Live Bus GPS Tracking & QR Boarding"),
    ("hostel", "Hostel & Room Allocation"),
    ("tpo", "Training, Placements (TPO) & Apprenticeships"),
    ("library", "Library & Book Circulation"),
    ("inventory", "Campus Inventory & Store"),
    ("analytics", "Institutional Analytics & OBE Reports"),
    ("announcements", "Campus Announcements & Broadcasts"),
    ("audit-logs", "Security & Activity Audit Logs"),
]


def _get_tenant_counts(tenant):
    """Safely fetch active student and staff counts for a tenant schema."""
    if not tenant.schema_name or tenant.schema_name == "public":
        return {"students": 0, "employees": 0}

    from campusflow_app.models.profile import (
        AdministratorProfile,
        DepartmentHeadProfile,
        ManagementProfile,
        NonTeachingStaffProfile,
        PrincipalProfile,
        StudentProfile,
        TeachingStaffProfile,
    )

    with schema_context(tenant.schema_name):
        try:
            students = StudentProfile.objects.count()
            employees = (
                TeachingStaffProfile.objects.count()
                + DepartmentHeadProfile.objects.count()
                + ManagementProfile.objects.count()
                + AdministratorProfile.objects.count()
                + PrincipalProfile.objects.count()
                + NonTeachingStaffProfile.objects.count()
            )
            return {"students": students, "employees": employees}
        except Exception:
            return {"students": 0, "employees": 0}


def render_tenant_legal_agreement_html(tenant):
    """
    Populate the CampusNexus Master Client Agreement HTML template with
    the given Tenant instance's attributes.
    """
    today_str = timezone.now().date().strftime("%d / %m / %Y")
    created_str = (
        tenant.created_on.strftime("%d / %m / %Y")
        if tenant.created_on
        else today_str
    )

    try:
        primary_domain_obj = tenant.get_primary_domain()
        primary_domain = (
            primary_domain_obj.domain
            if primary_domain_obj
            else f"{tenant.code or tenant.schema_name}.campusnexus.in"
        )
    except Exception:
        primary_domain = f"{tenant.code or tenant.schema_name}.campusnexus.in"

    tenant_name = html.escape(tenant.name or "[Institution Name]")
    tenant_code = html.escape((tenant.code or tenant.schema_name or "N/A").upper())
    tenant_address = html.escape(tenant.address or "[Campus Address, City, State, PIN]")
    tenant_email = html.escape(tenant.contact_email or "[Nodal Officer Email]")
    permitted_domain = html.escape(
        tenant.permitted_email_domain or f"{tenant.code or 'college'}.edu.in"
    )
    tenant_type_label = html.escape(tenant.get_tenant_type_display() or "College")

    # Billing rates
    student_rate = Decimal(str(tenant.billing_student_rate or "50.00"))
    student_discount = Decimal(str(tenant.billing_student_discount or "10.00"))
    net_student_rate = max(Decimal("0.00"), student_rate - student_discount)

    employee_rate = Decimal(str(tenant.billing_employee_rate or "100.00"))
    employee_discount = Decimal(str(tenant.billing_employee_discount or "100.00"))

    counts = _get_tenant_counts(tenant)
    student_count = counts["students"]
    employee_count = counts["employees"]

    est_student_monthly = student_count * net_student_rate
    est_employee_monthly = max(
        Decimal("0.00"), (employee_count * employee_rate) - employee_discount
    )
    est_total_monthly = est_student_monthly + est_employee_monthly

    # Billing cycle & trial dates
    is_annual = tenant.billing_cycle == "annual"
    is_monthly = not is_annual
    initial_term_months = "12" if is_annual else "1"

    trial_start_str = (
        tenant.trial_start_date.strftime("%d / %m / %Y")
        if tenant.trial_start_date
        else created_str
    )
    trial_end_str = (
        tenant.trial_end_date.strftime("%d / %m / %Y")
        if tenant.trial_end_date
        else "N/A"
    )
    sub_end_str = (
        tenant.subscription_end_date.strftime("%d / %m / %Y")
        if tenant.subscription_end_date
        else "As per Invoice"
    )

    # Payment gateway details
    gateway_label = html.escape(tenant.get_payment_gateway_active_display() or "Manual")
    absorb_checked = "checked" if tenant.fee_surcharge_mode == "absorb" else ""
    pass_checked = "checked" if tenant.fee_surcharge_mode == "pass_to_student" else ""
    convenience_pct = Decimal(str(tenant.convenience_fee_percent or "0.00"))

    # Subscribed modules
    raw_modules = tenant.subscribed_modules or []
    normalized_subscribed = {str(m).strip().lower() for m in raw_modules}

    module_items_html = []
    for mod_key, mod_label in MODULE_CATALOG:
        is_checked = (
            not normalized_subscribed
            or mod_key.lower() in normalized_subscribed
            or mod_label.lower() in normalized_subscribed
        )
        checked_attr = "checked" if is_checked else ""
        module_items_html.append(
            f'<label class="module-item">'
            f'<input type="checkbox" {checked_attr} /> {html.escape(mod_label)}'
            f'</label>'
        )
    modules_grid_content = "\n        ".join(module_items_html)

    monthly_checked = "checked" if is_monthly else ""
    annual_checked = "checked" if is_annual else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>CampusNexus — Master Client Legal Agreement ({tenant_name})</title>
  <style>
    :root {{
      --ink: #0f172a;
      --ink-secondary: #334155;
      --ink-muted: #64748b;
      --accent: #1e3a8a;
      --accent-light: #eff6ff;
      --border: #cbd5e1;
      --bg-page: #f1f5f9;
      --bg-paper: #ffffff;
      --warning-bg: #fffbeb;
      --warning-border: #f59e0b;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      padding: 0;
      background-color: var(--bg-page);
      color: var(--ink);
      font-family: "Georgia", "Times New Roman", Times, serif;
      line-height: 1.65;
      font-size: 11pt;
    }}

    .toolbar {{
      position: sticky;
      top: 0;
      z-index: 100;
      background: #0f172a;
      color: #ffffff;
      padding: 12px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
    }}

    .toolbar-Left {{
      display: flex;
      align-items: center;
      gap: 14px;
    }}

    .toolbar-title {{
      font-weight: 700;
      font-size: 15px;
      letter-spacing: 0.3px;
    }}

    .toolbar-badge {{
      background: #1d4ed8;
      color: #e0e7ff;
      font-size: 11px;
      padding: 3px 8px;
      border-radius: 4px;
      font-weight: 600;
      text-transform: uppercase;
    }}

    .toolbar-nav {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}

    .toolbar-nav a {{
      color: #cbd5e1;
      text-decoration: none;
      font-size: 12px;
      padding: 5px 10px;
      border-radius: 4px;
      background: rgba(255, 255, 255, 0.08);
      transition: background 0.15s, color 0.15s;
    }}

    .toolbar-nav a:hover {{
      background: rgba(255, 255, 255, 0.18);
      color: #ffffff;
    }}

    .btn-print {{
      background: #2563eb;
      color: #ffffff;
      border: none;
      padding: 8px 16px;
      border-radius: 6px;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
      transition: background 0.15s;
    }}

    .btn-print:hover {{
      background: #1d4ed8;
    }}

    .document-wrapper {{
      max-width: 210mm;
      margin: 28px auto 60px auto;
      background: var(--bg-paper);
      padding: 22mm 20mm;
      box-shadow: 0 10px 30px rgba(15, 23, 42, 0.12);
      border: 1px solid #e2e8f0;
    }}

    .legal-disclaimer-banner {{
      background: var(--warning-bg);
      border-left: 4px solid var(--warning-border);
      padding: 12px 16px;
      margin-bottom: 24px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 9.5pt;
      color: #92400e;
    }}

    .doc-header {{
      text-align: center;
      border-bottom: 3px double var(--accent);
      padding-bottom: 18px;
      margin-bottom: 26px;
    }}

    .doc-header .doc-super {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 9pt;
      text-transform: uppercase;
      letter-spacing: 2px;
      color: var(--accent);
      font-weight: 700;
      margin-bottom: 6px;
    }}

    .doc-header h1 {{
      font-size: 20pt;
      margin: 6px 0 8px 0;
      color: var(--ink);
      letter-spacing: 0.3px;
      text-transform: uppercase;
    }}

    .doc-header .doc-subtitle {{
      font-size: 10.5pt;
      color: var(--ink-secondary);
      font-style: italic;
      margin: 0;
    }}

    .agreement-part {{
      margin-top: 32px;
      padding-top: 12px;
    }}

    .part-banner {{
      background: var(--accent);
      color: #ffffff;
      padding: 10px 16px;
      margin: 28px 0 18px 0;
      border-radius: 2px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }}

    .part-banner .part-label {{
      font-size: 8.5pt;
      text-transform: uppercase;
      letter-spacing: 1.5px;
      opacity: 0.85;
      display: block;
    }}

    .part-banner h2 {{
      margin: 2px 0 0 0;
      font-size: 13.5pt;
      font-weight: 700;
      letter-spacing: 0.2px;
    }}

    h3 {{
      font-size: 11.5pt;
      color: var(--accent);
      margin-top: 20px;
      margin-bottom: 8px;
      border-bottom: 1px solid #e2e8f0;
      padding-bottom: 4px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      text-transform: uppercase;
      letter-spacing: 0.4px;
    }}

    h4 {{
      font-size: 10.5pt;
      color: var(--ink);
      margin-top: 14px;
      margin-bottom: 4px;
      font-weight: 700;
    }}

    p {{
      margin: 0 0 10px 0;
      text-align: justify;
    }}

    ul, ol {{
      margin: 6px 0 12px 0;
      padding-left: 24px;
    }}

    li {{
      margin-bottom: 5px;
      text-align: justify;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 14px 0 18px 0;
      font-size: 10pt;
    }}

    th, td {{
      border: 1px solid var(--border);
      padding: 8px 10px;
      vertical-align: top;
      text-align: left;
    }}

    th {{
      background-color: var(--accent-light);
      color: var(--accent);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-weight: 700;
      font-size: 9.5pt;
      text-transform: uppercase;
    }}

    .fill-blank {{
      display: inline-block;
      min-width: 120px;
      border-bottom: 1px dashed #475569;
      padding: 0 6px;
      color: var(--accent);
      font-weight: 600;
    }}

    [contenteditable="true"]:focus {{
      outline: 2px solid #3b82f6;
      background: #eff6ff;
    }}

    .clause-box {{
      background: #f8fafc;
      border: 1px solid #cbd5e1;
      border-left: 4px solid var(--accent);
      padding: 12px 14px;
      margin: 12px 0;
      font-size: 10pt;
    }}

    .module-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 6px 12px;
      margin: 10px 0;
      font-size: 9.5pt;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }}

    .module-item {{
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 4px 6px;
      border: 1px solid #e2e8f0;
      background: #f8fafc;
    }}

    .signature-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
      margin-top: 28px;
      page-break-inside: avoid;
    }}

    .signature-card {{
      border: 1px solid var(--border);
      padding: 16px;
      background: #fafafa;
    }}

    .signature-card h4 {{
      margin-top: 0;
      border-bottom: 1px solid var(--border);
      padding-bottom: 6px;
      color: var(--accent);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      text-transform: uppercase;
      font-size: 9.5pt;
    }}

    .sig-line {{
      margin-top: 38px;
      border-bottom: 1px solid #334155;
      height: 24px;
    }}

    .page-break {{
      page-break-before: always;
    }}

    .toc-box {{
      background: #f8fafc;
      border: 1px solid var(--border);
      padding: 14px 18px;
      margin-bottom: 22px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 9.5pt;
    }}

    .toc-box h4 {{
      margin-top: 0;
      margin-bottom: 8px;
      text-transform: uppercase;
      color: var(--accent);
    }}

    .toc-box ol {{
      margin: 0;
      padding-left: 18px;
    }}

    .toc-box li {{
      margin-bottom: 4px;
    }}

    .toc-box a {{
      color: var(--ink);
      text-decoration: none;
    }}

    .toc-box a:hover {{
      text-decoration: underline;
      color: var(--accent);
    }}

    @media print {{
      body {{
        background: #ffffff;
        font-size: 10.5pt;
      }}
      .no-print {{
        display: none !important;
      }}
      .document-wrapper {{
        max-width: 100%;
        margin: 0;
        padding: 0;
        box-shadow: none;
        border: none;
      }}
      @page {{
        size: A4;
        margin: 18mm 16mm 18mm 16mm;
      }}
      a {{
        color: inherit;
        text-decoration: none;
      }}
    }}
  </style>
</head>
<body>

  <div class="toolbar no-print">
    <div class="toolbar-Left">
      <span class="toolbar-title">CampusNexus Legal Suite — {tenant_name}</span>
      <span class="toolbar-badge">SaaS Owner Generated Contract</span>
    </div>
    <nav class="toolbar-nav">
      <a href="#order-form">Order Form</a>
      <a href="#part-1">1. Master SaaS MSA</a>
      <a href="#part-2">2. On-Premise License</a>
      <a href="#part-3">3. DPDP Data Protection</a>
      <a href="#part-4">4. SLA &amp; Support</a>
      <a href="#part-5">5. End-User Terms (EULA)</a>
      <a href="#signatures">Signatures</a>
    </nav>
    <button class="btn-print" onclick="window.print()">Print / Save as PDF</button>
  </div>

  <div class="document-wrapper">

    <div class="legal-disclaimer-banner no-print">
      <strong>Auto-Populated for {tenant_name} (Code: {tenant_code}):</strong> All fields (<span contenteditable="true" class="fill-blank">[Click to Edit]</span>) remain directly editable in your browser before printing. Click <strong>"Print / Save as PDF"</strong> in the top bar to generate a clean, paginated A4 PDF contract.
    </div>

    <div class="doc-header">
      <div class="doc-super">Comprehensive Institutional Software &amp; Services Contract</div>
      <h1>Master Client Agreement &amp; Schedules</h1>
      <p class="doc-subtitle">
        Governing Cloud SaaS Subscriptions, On-Premise Deployments, Data Processing (DPDP Act, 2023),
        Service Level Commitments, and End-User Terms for the CampusNexus ERP Platform
      </p>
    </div>

    <div class="toc-box">
      <h4>Structure of this Agreement</h4>
      <ol>
        <li><a href="#order-form"><strong>Commercial Order Form &amp; Institutional Schedule</strong> — Parties, Subscribed Modules, Pricing &amp; Payment Gateway Election</a></li>
        <li><a href="#part-1"><strong>Part I: Master SaaS Subscription &amp; Services Agreement (MSA)</strong> — Cloud Multi-Tenant Terms, Billing, IP &amp; Liability</a></li>
        <li><a href="#part-2"><strong>Part II: On-Premise / Self-Hosted Software License Addendum</strong> — Server License, Source/Binary Protection &amp; Maintenance</a></li>
        <li><a href="#part-3"><strong>Part III: Data Processing Agreement (DPA) &amp; Student Privacy</strong> — DPDP Act 2023, Biometric/Face Liveness, GPS &amp; Minor Consent</a></li>
        <li><a href="#part-4"><strong>Part IV: Service Level Agreement (SLA) &amp; Support Policy</strong> — Uptime Commitments, Severity Tiers, Backups &amp; Service Credits</a></li>
        <li><a href="#part-5"><strong>Part V: End-User Acceptable Use &amp; Terms of Service (EULA)</strong> — Terms Binding Students, Faculty, Staff &amp; Guardians</a></li>
      </ol>
    </div>

    <section id="order-form">
      <h3>Commercial Order Form &amp; Institutional Details</h3>
      <p>
        This Master Client Agreement (the <strong>"Agreement"</strong>) is entered into and made effective as of
        <span contenteditable="true" class="fill-blank">{today_str}</span> (the <strong>"Effective Date"</strong>),
        by and between:
      </p>

      <table>
        <thead>
          <tr>
            <th style="width: 50%;">Service Provider / Licensor ("Provider")</th>
            <th style="width: 50%;">Educational Institution / Client ("Client" / "Institution")</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <strong>Legal Entity Name:</strong> <span contenteditable="true" class="fill-blank">Polynexus Technologies Private Limited</span><br />
              <strong>CIN / Registration No.:</strong> <span contenteditable="true" class="fill-blank">[U72200XXXXXXXXXXXX]</span><br />
              <strong>GSTIN:</strong> <span contenteditable="true" class="fill-blank">[27XXXXX0000X1Z5]</span><br />
              <strong>PAN:</strong> <span contenteditable="true" class="fill-blank">[ABCDE1234F]</span><br />
              <strong>Registered Office:</strong> <span contenteditable="true" class="fill-blank">[Full Registered Address, City, State, PIN]</span><br />
              <strong>Authorized Contact Email:</strong> <span contenteditable="true" class="fill-blank">admin@polynexus.in</span>
            </td>
            <td>
              <strong>Institution / Trust / Society Name:</strong> <span contenteditable="true" class="fill-blank">{tenant_name}</span><br />
              <strong>Tenant / Institution Code:</strong> <span contenteditable="true" class="fill-blank">{tenant_code}</span><br />
              <strong>GSTIN / TAN:</strong> <span contenteditable="true" class="fill-blank">[Client GSTIN / TAN]</span><br />
              <strong>Institution Type:</strong> <span contenteditable="true" class="fill-blank">{tenant_type_label}</span><br />
              <strong>Campus Address:</strong> <span contenteditable="true" class="fill-blank">{tenant_address}</span><br />
              <strong>Nodal Officer &amp; Email:</strong> <span contenteditable="true" class="fill-blank">{tenant_email}</span>
            </td>
          </tr>
        </tbody>
      </table>

      <h4>A. Deployment Mode &amp; Tenancy Configuration</h4>
      <table>
        <tbody>
          <tr>
            <th style="width: 28%;">Deployment Model</th>
            <td>
              <label><input type="checkbox" checked /> <strong>Multi-Tenant Cloud SaaS</strong> (Dedicated PostgreSQL Tenant Schema: <code>{html.escape(tenant.schema_name)}</code>)</label><br />
              <label><input type="checkbox" /> <strong>Dedicated Private Cloud / Single-Tenant Instance</strong></label><br />
              <label><input type="checkbox" /> <strong>On-Premise / Self-Hosted License</strong> (Subject to Part II of this Agreement)</label>
            </td>
          </tr>
          <tr>
            <th>Primary Tenant Domain(s)</th>
            <td>
              <code>https://<span contenteditable="true" class="fill-blank">{html.escape(primary_domain)}</span></code> &nbsp;|&nbsp;
              Permitted Student Email Domain: <code>@<span contenteditable="true" class="fill-blank">{permitted_domain}</span></code>
            </td>
          </tr>
          <tr>
            <th>Subscription Term &amp; Cycle</th>
            <td>
              <strong>Initial Term:</strong> <span contenteditable="true" class="fill-blank">{initial_term_months}</span> Months &nbsp;|&nbsp;
              <strong>Billing Cycle:</strong> <label><input type="checkbox" {monthly_checked} /> Monthly</label> &nbsp; <label><input type="checkbox" {annual_checked} /> Annual</label> &nbsp;|&nbsp;
              <strong>Trial / Valid Until:</strong> <span contenteditable="true" class="fill-blank">{trial_start_str}</span> to <span contenteditable="true" class="fill-blank">{sub_end_str if tenant.subscription_end_date else trial_end_str}</span>
            </td>
          </tr>
        </tbody>
      </table>

      <h4>B. Subscribed Platform Modules (`subscribed_modules`)</h4>
      <div class="module-grid">
        {modules_grid_content}
      </div>

      <h4>C. Commercial Pricing &amp; Fee Structure (Excluding Applicable GST @ 18%)</h4>
      <table>
        <thead>
          <tr>
            <th>Billing Component</th>
            <th>Base Rate (INR)</th>
            <th>Agreed Discount</th>
            <th>Net Payable Rate (INR)</th>
            <th>Current Directory Count &amp; Est. Monthly Subtotal</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Active Student Rate</strong></td>
            <td>&#8377; <span contenteditable="true" class="fill-blank">{student_rate:.2f}</span> / student</td>
            <td>&#8377; <span contenteditable="true" class="fill-blank">{student_discount:.2f}</span> / student</td>
            <td>&#8377; <span contenteditable="true" class="fill-blank">{net_student_rate:.2f}</span> / student</td>
            <td>{student_count} active students &rarr; <strong>&#8377; <span contenteditable="true" class="fill-blank">{est_student_monthly:,.2f}</span> / month</strong></td>
          </tr>
          <tr>
            <td><strong>Active Employee / Faculty Rate</strong></td>
            <td>&#8377; <span contenteditable="true" class="fill-blank">{employee_rate:.2f}</span> / staff</td>
            <td>&#8377; <span contenteditable="true" class="fill-blank">{employee_discount:.2f}</span> flat discount</td>
            <td>&#8377; <span contenteditable="true" class="fill-blank">{est_employee_monthly:.2f}</span> net</td>
            <td>{employee_count} active staff &rarr; <strong>&#8377; <span contenteditable="true" class="fill-blank">{est_employee_monthly:,.2f}</span> / month</strong></td>
          </tr>
          <tr>
            <td><strong>Estimated Total Monthly SaaS Subscription</strong></td>
            <td colspan="3">Dynamic calculation based on active student &amp; employee directory counts</td>
            <td><strong>&#8377; <span contenteditable="true" class="fill-blank">{est_total_monthly:,.2f}</span> / month</strong> (+ GST)</td>
          </tr>
          <tr>
            <td><strong>One-Time Onboarding &amp; Migration Fee</strong></td>
            <td>&#8377; <span contenteditable="true" class="fill-blank">25,000.00</span></td>
            <td><span contenteditable="true" class="fill-blank">0%</span></td>
            <td>&#8377; <span contenteditable="true" class="fill-blank">25,000.00</span></td>
            <td>Includes tenant provisioning, initial CSV data import &amp; admin training</td>
          </tr>
          <tr>
            <td><strong>Fee Payment Gateway Election</strong></td>
            <td colspan="4">
              Selected Gateway: <span contenteditable="true" class="fill-blank">{gateway_label}</span> &nbsp;|&nbsp;
              Surcharge Mode: <label><input type="checkbox" {absorb_checked} /> Absorb by Institution</label> / <label><input type="checkbox" {pass_checked} /> Pass Convenience Fee (<span contenteditable="true" class="fill-blank">{convenience_pct:.2f}</span>%) to Student</label>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section id="part-1" class="agreement-part page-break">
      <div class="part-banner">
        <span class="part-label">Part I of V</span>
        <h2>Master SaaS Subscription &amp; Services Agreement (MSA)</h2>
      </div>

      <h3>1. Definitions &amp; Interpretation</h3>
      <p>
        <strong>1.1 "Platform" or "Software"</strong> means the proprietary <em>CampusNexus</em> academic, administrative, and enterprise resource planning (ERP) web and mobile software applications, APIs, database schemas, algorithms (including automated timetable generation, OBE attainment calculation, and biometric liveness verification pipelines), and documentation owned and operated by Provider.
      </p>
      <p>
        <strong>1.2 "Tenant Environment"</strong> means the logically isolated PostgreSQL schema and dedicated subdomain provisioned exclusively for the Client within Provider's multi-tenant cloud architecture.
      </p>
      <p>
        <strong>1.3 "Authorized Users"</strong> means the Client's officially enrolled Students, Management, Principal, Administrators, Department Heads (HODs), Teaching Staff, Non-Teaching Staff, Bus Drivers/Conductors, and verified Parents/Legal Guardians to whom the Client grants role-based access credentials.
      </p>
      <p>
        <strong>1.4 "Institutional Data"</strong> means all electronic data, academic records, attendance logs, biometric templates, fee records, payroll structures, question banks, and personally identifiable information uploaded, submitted, or generated by or on behalf of the Client and its Authorized Users on the Platform.
      </p>

      <h3>2. Scope of Services &amp; License Grant</h3>
      <p>
        <strong>2.1 SaaS Access Grant:</strong> Subject to timely payment of all applicable fees and continuous compliance with this Agreement, Provider grants the Client a revocable, non-exclusive, non-transferable, non-sublicensable right during the Subscription Term to access and use the Subscribed Modules of the Platform specified in the Commercial Order Form solely for the Client's internal institutional operations.
      </p>
      <p>
        <strong>2.2 Module-Level Access Control:</strong> Access to functional modules is governed programmatically by the Client's active subscription configuration (<code>subscribed_modules</code>) and Role-Based Access Control (RBAC) policies. Modules not subscribed to in the Order Form shall remain disabled unless added via a written or digital Change Order.
      </p>
      <p>
        <strong>2.3 Trial &amp; Sandbox Tenants:</strong> Where the Client is initially provisioned a Trial Period or access to a shared Public Demo Tenant (<code>is_demo</code>), such access is provided strictly "AS-IS" for evaluation. Provider reserves the right to restrict destructive configuration changes, outbound SMTP email dispatch, and credential modifications within demo environments. Unless converted to a paid subscription prior to the Trial End Date, trial access shall automatically suspend upon expiration.
      </p>

      <h3>3. B2B Billing, Invoicing &amp; Taxes</h3>
      <p>
        <strong>3.1 Usage Calculation:</strong> Subscription fees are calculated based on the number of active Student and Employee accounts registered in the Client's Tenant Environment during the relevant Billing Period multiplied by the Net Payable Rates specified in the Commercial Order Form, plus any fixed module or annual base charges.
      </p>
      <p>
        <strong>3.2 Invoicing &amp; Offline RTGS/NEFT Settlement:</strong> Provider shall issue electronic B2B invoices via the Platform's SaaS Billing Portal. Unless paid via an integrated B2B payment link, the Client shall remit payment via NEFT, RTGS, or IMPS to Provider's designated bank account on or before the Invoice Due Date (defaulting to fifteen (15) calendar days from the invoice date) and upload the corresponding bank payment receipt and Unique Transaction Reference (<strong>"UTR Number"</strong>) into the Platform for verification and reconciliation.
      </p>
      <p>
        <strong>3.3 Taxes &amp; TDS:</strong> All stated fees are exclusive of Goods and Services Tax (<strong>"GST"</strong>) and other applicable statutory levies, which shall be charged additionally at prevailing rates. If the Client is required under the Indian Income Tax Act, 1961 to deduct Tax Deducted at Source (<strong>"TDS"</strong>), the Client shall remit such TDS to the Government of India on time and furnish valid Form 16A certificates to Provider within statutory timelines so Provider can claim full tax credit.
      </p>
      <p>
        <strong>3.4 Late Payment &amp; Account Suspension:</strong> Invoices remaining unpaid beyond the Due Date shall transition to <code>overdue</code> status and may accrue late interest at 1.5% per month (or the maximum rate permitted by law). If an invoice remains unpaid for more than fifteen (15) days past the Due Date following written notice, Provider reserves the right to transition the Tenant's <code>subscription_status</code> to <code>suspended</code>, restricting Platform access to read-only or administrative billing views until full settlement is verified.
      </p>

      <h3>4. Third-Party Integrations &amp; Student Fee Payment Gateways</h3>
      <p>
        <strong>4.1 Payment Gateway Merchant Accounts:</strong> The Platform supports direct integration with third-party payment aggregators (including Razorpay, Cashfree, PayU, PhonePe, Paytm, and MobiKwik/Zaakpay) to enable the Client to collect tuition, hostel, transport, and examination fees from students. The Client acknowledges that:
      </p>
      <ul>
        <li>The Client is the direct Merchant of Record with the chosen Payment Gateway and is solely responsible for maintaining its KYC, nodal bank settlement accounts, and merchant agreements;</li>
        <li>API keys, merchant salts, and webhook secrets entered by the Client are stored using field-level encryption (<code>EncryptedCharField</code>) within the Platform;</li>
        <li>Provider is a technology facilitator and is not a bank, payment system operator, or payment aggregator under Reserve Bank of India (RBI) regulations;</li>
        <li>All student fee settlements, chargebacks, refunds, failed split-settlements, and Merchant Discount Rate (MDR) disputes are strictly between the Client, the Payer, and the respective Payment Gateway provider; and</li>
        <li>Whether the Client elects to absorb gateway transaction costs (<code>absorb</code>) or pass a convenience fee percentage to the student payer (<code>pass_to_student</code>), the Client is solely responsible for ensuring such election complies with applicable university/board fee regulations and gateway merchant rules.</li>
      </ul>
      <p>
        <strong>4.2 Custom SMTP &amp; Legacy ERP Connectors:</strong> Where the Client configures its own SMTP mail credentials or third-party ERP API connectors (e.g., SAP, Banner, Tally, or custom webhooks), the Client is solely responsible for the availability, rate limits, security, and licensing of such external systems.
      </p>

      <h3>5. Intellectual Property Rights &amp; Restrictions</h3>
      <p>
        <strong>5.1 Provider IP Ownership:</strong> Provider retains all right, title, and interest (including all copyrights, patents, trade secrets, trademarks, source code, database designs, and UI/UX layouts) in and to the Platform, documentation, and any customizations, enhancements, or derivative works created during the Term. No rights are granted to the Client other than those expressly set forth herein.
      </p>
      <p>
        <strong>5.2 Ownership of Institutional Data:</strong> As between the Parties, the Client retains exclusive ownership of all right, title, and interest in and to its Institutional Data. The Client grants Provider a limited, royalty-free license during the Term to host, process, transmit, back up, and display Institutional Data solely as necessary to provide and improve the Services under this Agreement.
      </p>
      <p>
        <strong>5.3 Prohibited Conduct:</strong> The Client shall not, and shall not permit any Authorized User or third party to: (a) copy, modify, decompile, disassemble, or reverse-engineer any part of the Platform; (b) bypass tenant isolation, API rate limits, device-binding locks, or biometric anti-spoofing/liveness checks; (c) rent, lease, timeshare, or resell the Platform to unaffiliated institutions; or (d) use the Platform to store or transmit unlawful, defamatory, or infringing material or malicious code.
      </p>

      <h3>6. Confidentiality</h3>
      <p>
        Each Party (as "Receiving Party") agrees to hold in strict confidence all non-public technical, financial, commercial, security, and student/staff data disclosed by the other Party (as "Disclosing Party"), exercising at least the same degree of care as it uses to protect its own confidential information of like importance, and in no event less than reasonable care. Confidential Information shall not be disclosed to any third party except to employees, auditors, legal counsel, or authorized cloud sub-processors bound by written confidentiality obligations no less protective than those herein, or as compelled by a court or statutory authority of competent jurisdiction after giving prompt notice to the Disclosing Party.
      </p>

      <h3>7. Warranties, Indemnification &amp; Limitation of Liability</h3>
      <p>
        <strong>7.1 Mutual Warranties:</strong> Each Party represents and warrants that it is duly organized, validly existing, and has full legal authority to enter into and perform this Agreement without violating any applicable law, university statute, trust deed, or third-party contract.
      </p>
      <p>
        <strong>7.2 Disclaimer:</strong> EXCEPT AS EXPRESSLY PROVIDED IN THIS AGREEMENT AND THE SLA (PART IV), THE PLATFORM IS PROVIDED ON AN "AS-IS" AND "AS-AVAILABLE" BASIS WITHOUT WARRANTIES OF ANY KIND, WHETHER EXPRESS, IMPLIED, OR STATUTORY, INCLUDING IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, OR NON-INFRINGEMENT.
      </p>
      <p>
        <strong>7.3 Indemnification:</strong> Provider shall defend and indemnify the Client against any third-party claim alleging that the unmodified Platform directly infringes a valid Indian copyright or patent. Conversely, the Client shall defend and indemnify Provider against any third-party or regulatory claim arising out of: (a) the Client's failure to obtain lawful consent or provide required notices to Authorized Users or Guardians as required under Part III; (b) inaccuracies or unlawful content in Institutional Data uploaded by the Client; or (c) fee disputes, refund claims, or employment/payroll disputes between the Client and its students or staff.
      </p>
      <p>
        <strong>7.4 Limitation of Liability:</strong> TO THE MAXIMUM EXTENT PERMITTED BY INDIAN LAW: (A) NEITHER PARTY SHALL BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, EXEMPLARY, OR PUNITIVE DAMAGES, OR LOSS OF PROFITS, REVENUE, OR GOODWILL; AND (B) PROVIDER'S AGGREGATE CUMULATIVE LIABILITY ARISING OUT OF OR RELATING TO THIS AGREEMENT SHALL NOT EXCEED THE TOTAL SUBSCRIPTION FEES ACTUALLY PAID BY THE CLIENT TO PROVIDER IN THE TWELVE (12) MONTHS IMMEDIATELY PRECEDING THE EVENT GIVING RISE TO THE CLAIM.
      </p>

      <h3>8. Term, Termination &amp; Data Offboarding</h3>
      <p>
        <strong>8.1 Term &amp; Renewal:</strong> This Agreement commences on the Effective Date and continues for the Initial Term specified in the Commercial Order Form. Thereafter, it shall automatically renew for successive periods equal to the Initial Term unless either Party gives written notice of non-renewal at least thirty (30) days prior to the expiration of the then-current Term.
      </p>
      <p>
        <strong>8.2 Termination for Cause:</strong> Either Party may terminate this Agreement immediately upon written notice if the other Party: (a) commits a material breach of this Agreement that remains uncured thirty (30) days after written notice specifying the breach; or (b) becomes insolvent, enters liquidation, or undergoes corporate insolvency resolution proceedings under the Insolvency and Bankruptcy Code, 2016.
      </p>
      <p>
        <strong>8.3 Post-Termination Data Export &amp; Purge:</strong> Upon expiration or termination of this Agreement (and subject to settlement of all undisputed outstanding invoices), Provider shall make the Client's Institutional Data available for export in standard machine-readable formats (CSV / JSON / SQL dump / PDF transcripts) for a transition window of thirty (30) calendar days. Following the expiry of such 30-day window, Provider shall permanently delete and purge the Client's Tenant Schema and associated media files from active servers within sixty (60) days, except to the extent retention is mandated by applicable Indian law.
      </p>

      <h3>9. Governing Law, Dispute Resolution &amp; General Provisions</h3>
      <p>
        <strong>9.1 Governing Law &amp; Jurisdiction:</strong> This Agreement shall be governed by and construed in accordance with the laws of the Republic of India, including the Indian Contract Act, 1872, the Information Technology Act, 2000, and the Digital Personal Data Protection Act, 2023. Subject to Section 9.2, the courts at <span contenteditable="true" class="fill-blank">[City, State, India]</span> shall have exclusive jurisdiction.
      </p>
      <p>
        <strong>9.2 Arbitration:</strong> Any dispute, controversy, or claim arising out of or relating to this Agreement that is not resolved amicably within thirty (30) days of written notice shall be referred to and finally resolved by binding arbitration under the <em>Arbitration and Conciliation Act, 1996</em> by a sole arbitrator mutually appointed by the Parties. The seat and venue of arbitration shall be <span contenteditable="true" class="fill-blank">[City, State, India]</span>, and the proceedings shall be conducted in the English language.
      </p>
      <p>
        <strong>9.3 Force Majeure:</strong> Neither Party shall be liable for delays or failures in performance (excluding payment obligations) caused by events beyond its reasonable control, including acts of God, natural disasters, pandemics, government orders, nationwide telecommunications or upstream cloud backbone outages, or acts of war or terrorism.
      </p>
    </section>

    <section id="part-2" class="agreement-part page-break">
      <div class="part-banner">
        <span class="part-label">Part II of V</span>
        <h2>On-Premise / Self-Hosted Software License Addendum</h2>
      </div>
      <div class="clause-box">
        <strong>Applicability:</strong> This Part II applies <em>only</em> if the Client has elected the <strong>On-Premise / Self-Hosted License</strong> deployment model in the Commercial Order Form (or subsequently migrates to an on-premise deployment via a written addendum).
      </div>

      <h3>1. Grant of On-Premise License</h3>
      <p>
        <strong>1.1 Designated Server License:</strong> Subject to payment of the applicable On-Premise License Fee and Annual Maintenance Contract (<strong>"AMC"</strong>) Fee, Provider grants the Client a non-exclusive, non-transferable license during the License Term to install and execute one (1) production instance and one (1) staging/backup instance of the Software on physical or virtual server infrastructure owned or leased exclusively by the Client at the Designated Campus Location(s).
      </p>
      <p>
        <strong>1.2 Institution &amp; User Scope:</strong> The On-Premise License is restricted strictly to the legal entity and campus code(s) identified in the Order Form and may not be used to host multi-tenant instances for sister institutions, affiliated colleges, or external trusts unless an Enterprise Multi-Campus License has been explicitly purchased.
      </p>

      <h3>2. Source Code, Container Images &amp; Intellectual Property Protection</h3>
      <p>
        <strong>2.1 Delivery Format:</strong> Provider may deliver the Software via encrypted Docker containers, compiled Python bytecode/wheels, or restricted deployment repositories. Unless a separate Source Code Escrow Agreement is executed, the Client acquires no ownership or modification rights over the underlying source code.
      </p>
      <p>
        <strong>2.2 Protection of Deployment Artifacts:</strong> The Client shall restrict root, SSH, and database administrative access on the host servers strictly to authorized IT personnel bound by confidentiality obligations. The Client shall not distribute, publish, push to public Git repositories, or permit third-party vendors to copy or inspect the Software's application containers, database migrations, or proprietary algorithms.
      </p>
      <p>
        <strong>2.3 License Verification &amp; Audit:</strong> The Software may include automated license-key validation or periodic seat-count reporting. Upon fifteen (15) days' prior written notice and no more than once per calendar year, Provider may audit the Client's server deployment (remotely or on-site during normal academic hours) to verify compliance with licensed student/staff counts and module entitlements.
      </p>

      <h3>3. Client Infrastructure &amp; Security Responsibilities</h3>
      <p>
        When deployed On-Premise, the Client assumes sole and complete responsibility for:
      </p>
      <ul>
        <li>Provisioning and maintaining server hardware, Linux OS security patches, PostgreSQL database administration, Redis queues, SSL/TLS certificates, and firewall/VPN perimeter security;</li>
        <li>Configuring daily automated off-site backups of the PostgreSQL database and local media storage (including uploaded documents, answer scripts, and facial embeddings);</li>
        <li>Physical security of the campus server room, uninterrupted power supply (UPS), and network bandwidth required for concurrent exam, attendance, or fee collection peaks; and</li>
        <li>Fulfilling all statutory data localization, cybersecurity incident reporting (including CERT-In directives), and physical access controls required under Indian law.</li>
      </ul>

      <h3>4. Annual Maintenance Contract (AMC) &amp; Version Upgrades</h3>
      <p>
        <strong>4.1 AMC Scope:</strong> Subject to payment of the annual AMC Fee (calculated at <span contenteditable="true" class="fill-blank">[20%]</span> of the base license value per annum unless otherwise stated in the Order Form), Provider shall provide: (a) minor point releases, security patches, and bug fixes; (b) remote troubleshooting assistance via secure screen-share or VPN tunnel; and (c) compatibility updates for supported third-party payment gateways.
      </p>
      <p>
        <strong>4.2 Exclusions from AMC:</strong> Provider shall have no obligation to support or repair failures caused by: (a) unauthorized modification of the Software code or direct manipulation of PostgreSQL database tables by the Client's personnel; (b) hardware failure, ransomware/malware infection on the Client's local network, or operating system corruption; or (c) failure by the Client to install recommended security updates within sixty (60) days of release.
      </p>
    </section>

    <section id="part-3" class="agreement-part page-break">
      <div class="part-banner">
        <span class="part-label">Part III of V</span>
        <h2>Data Processing Agreement (DPA) &amp; Student Privacy Compliance</h2>
      </div>
      <div class="clause-box">
        <strong>Statutory Alignment:</strong> Pursuant to the <strong>Digital Personal Data Protection Act, 2023 ("DPDP Act")</strong> and the <strong>Information Technology Act, 2000</strong> (including the IT (Reasonable Security Practices and Procedures and Sensitive Personal Data or Information) Rules, 2011).
      </div>

      <h3>1. Statutory Roles of the Parties</h3>
      <p>
        <strong>1.1 Data Fiduciary &amp; Data Processor:</strong> With respect to all Personal Data contained within Institutional Data:
      </p>
      <ul>
        <li>The <strong>Client ({tenant_name})</strong> acts as the <strong>"Data Fiduciary"</strong> (as defined under Section 2(i) of the DPDP Act, 2023), as the Client determines the purpose and means of processing student, guardian, applicant, and employee personal data for academic and institutional administration; and</li>
        <li>The <strong>Provider (Polynexus Technologies Private Limited)</strong> acts strictly as a <strong>"Data Processor"</strong> (as defined under Section 2(k) of the DPDP Act, 2023), processing Personal Data solely on behalf of and in accordance with the documented instructions and configurations of the Client.</li>
      </ul>

      <h3>2. Categories of Data Principals &amp; Personal Data Processed</h3>
      <table>
        <thead>
          <tr>
            <th style="width: 22%;">Data Category</th>
            <th style="width: 38%;">Specific Data Elements Processed in CampusNexus</th>
            <th style="width: 40%;">Specified Lawful Purpose</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Identity &amp; Academic Records</strong></td>
            <td>Full name, enrollment/roll number, email, phone number, photograph, date of birth, department, batch, attendance, exam marks, OBE attainment, assignments, disciplinary/clearance status, and placement (TPO) profiles.</td>
            <td>Core academic lifecycle administration, grading, transcript generation, university compliance, and campus placement facilitation.</td>
          </tr>
          <tr>
            <td><strong>Biometric &amp; Liveness Data</strong></td>
            <td>Facial recognition feature embeddings/vectors and camera liveness verification challenges captured via <code>FaceRegistrationView</code> and <code>MarkAttendanceView</code>.</td>
            <td>Anti-proxy student/lecturer attendance verification and identity authentication during classroom check-ins.</td>
          </tr>
          <tr>
            <td><strong>Geolocation &amp; Device Telemetry</strong></td>
            <td>Classroom check-in GPS coordinates (<code>ClassroomLocationValidationView</code>), live school/college bus GPS trails (<code>BusLiveLocationsView</code>), QR boarding scans, IP addresses, and cryptographic device-lock identifiers.</td>
            <td>Verifying physical presence within designated classroom geofences, preventing multi-device credential sharing, and providing real-time student transit safety to Guardians.</td>
          </tr>
          <tr>
            <td><strong>Financial &amp; Payroll Data</strong></td>
            <td>Student fee invoices, scholarship/discount details, payment gateway transaction references, UTR receipts, employee salary structures, deductions, and generated payslips.</td>
            <td>Institutional fee collection, accounting reconciliation, and staff payroll administration.</td>
          </tr>
          <tr>
            <td><strong>Guardian &amp; Minor Data</strong></td>
            <td>Parent/Legal Guardian contact details, relationship link records, and digital consent audit logs (<code>GuardianConsentApprovalView</code>).</td>
            <td>Parent communication, attendance correction requests, bus tracking visibility, and verifiable parental consent under Section 9 of the DPDP Act.</td>
          </tr>
        </tbody>
      </table>

      <h3>3. Special Provisions for Biometric, Geolocation &amp; Children's Data</h3>
      <p>
        <strong>3.1 Verifiable Parental Consent for Minors (Section 9, DPDP Act 2023):</strong> Before processing the Personal Data of any Student who is a "Child" (an individual under the age of eighteen (18) years under Indian law), the Client (as Data Fiduciary) shall ensure that verifiable consent of the Parent or Lawful Guardian is obtained. The Platform provides built-in workflows for guardian onboarding, parent-student linking, and guardian consent recording (<code>GuardianConsentApprovalView</code>, <code>UserGrantConsentView</code>). Neither Party shall undertake any processing of a Child's personal data that is likely to cause any detrimental effect on the well-being of the Child or engage in behavioural monitoring or targeted advertising directed at Children.
      </p>
      <p>
        <strong>3.2 Biometric Facial Attendance Safeguards:</strong> Where the Client enables the Biometric Face Attendance module:
      </p>
      <ul>
        <li>Facial captures are processed solely to generate mathematical facial feature vectors/embeddings and perform liveness anti-spoofing verification;</li>
        <li>Biometric data is never sold, shared with external marketing entities, or used for cross-institutional surveillance;</li>
        <li>The Client shall provide an alternative manual attendance mechanism (supported via <code>StudentRequestManualAttendanceView</code> and <code>LecturerApproveManualRequestView</code>) for any student who experiences technical capture failure or validly withholds/withdraws biometric consent; and</li>
        <li>Upon a student's graduation, withdrawal, or exercise of consent withdrawal/erasure, all associated biometric facial templates shall be purged from the active database.</li>
      </ul>
      <p>
        <strong>3.3 Purpose-Bound Geolocation Tracking:</strong> Classroom geolocation checks are performed strictly at the moment of attendance check-in to validate proximity to the configured classroom coordinates, and continuous background tracking of student personal devices outside attendance sessions is prohibited. Live Bus GPS tracking operates solely during active bus trips started by authorized transport staff (<code>BusTripStartView</code> to <code>BusTripEndView</code>).
      </p>

      <h3>4. Data Principal Rights &amp; Platform Compliance Tooling</h3>
      <p>
        Provider has engineered native API endpoints into the Platform to assist the Client in fulfilling Data Principal rights under Chapter III of the DPDP Act, 2023, including:
      </p>
      <ul>
        <li><strong>Right to Grant &amp; Withdraw Consent:</strong> Tracked via <code>UserGrantConsentView</code> and <code>UserWithdrawConsentView</code> with immutable timestamped audit logs;</li>
        <li><strong>Right to Correction &amp; Erasure:</strong> Supported via profile update workflows, attendance correction workflows, and <code>UserDataErasureView</code> (subject to retention of mandatory academic transcripts/degree records required under UGC/AICTE/Board regulations); and</li>
        <li><strong>Grievance Redressal:</strong> The Client shall designate a Data Protection Officer / Nodal Grievance Officer whose contact details are made accessible to Authorized Users. Provider shall assist the Client in investigating and resolving any technical data privacy requests within seven (7) business days.</li>
      </ul>

      <h3>5. Technical &amp; Organizational Security Measures</h3>
      <p>
        Provider implements and maintains reasonable security practices and procedures commensurate with ISO/IEC 27001 standards and the IT Act, 2000, including:
      </p>
      <ul>
        <li><strong>Strict Multi-Tenant Schema Isolation:</strong> Each Client institution operates within an isolated PostgreSQL schema (`django-tenants`), preventing cross-tenant data leakage at the database layer;</li>
        <li><strong>Encryption in Transit &amp; at Rest:</strong> All API traffic is encrypted via TLS 1.2/1.3 (HTTPS), passwords are hashed using industry-standard salted cryptographic algorithms (PBKDF2/Argon2), and sensitive payment gateway secrets are encrypted at the field level (`EncryptedCharField`);</li>
        <li><strong>Role-Based Access &amp; Audit Logging:</strong> Granular RBAC permissions (`RoleModulePermissionView`) and comprehensive activity audit trails (`AuditLogListView`) tracking administrative actions; and</li>
        <li><strong>Personal Data Breach Notification:</strong> In the event of a confirmed Personal Data Breach affecting the Client's Tenant Environment, Provider shall notify the Client's Nodal Officer without undue delay and in no event later than <strong>forty-eight (48) hours</strong> after becoming aware of the breach, providing all forensic details required for the Client to fulfill its statutory reporting obligations to the Data Protection Board of India and CERT-In.</li>
      </ul>
    </section>

    <section id="part-4" class="agreement-part page-break">
      <div class="part-banner">
        <span class="part-label">Part IV of V</span>
        <h2>Service Level Agreement (SLA) &amp; Technical Support Policy</h2>
      </div>
      <div class="clause-box">
        <strong>Applicability:</strong> This Part IV governs cloud availability, backups, and technical support for <strong>Cloud SaaS Subscriptions</strong>.
      </div>

      <h3>1. System Availability Commitment</h3>
      <p>
        <strong>1.1 Target Monthly Uptime:</strong> Provider commits to maintaining a Monthly Uptime Percentage of at least <strong>99.5%</strong> for the production Cloud SaaS Platform during each calendar month of an active paid Subscription Term.
      </p>
      <p>
        <strong>1.2 Calculation of Monthly Uptime:</strong>
      </p>
      <div class="clause-box" style="text-align: center; font-weight: bold;">
        Monthly Uptime % = (Total Minutes in Calendar Month &minus; Unscheduled Downtime Minutes) &divide; (Total Minutes in Calendar Month) &times; 100
      </div>
      <p>
        <strong>1.3 SLA Exclusions ("Excused Downtime"):</strong> Unscheduled Downtime shall not include unavailability resulting from: (a) Scheduled Maintenance windows where at least twenty-four (24) hours' prior notice has been provided and which are conducted during non-peak academic hours (typically between 11:00 PM IST and 05:00 AM IST); (b) outages of third-party payment gateways, external SMS/SMTP providers, or the Client's campus internet service provider; (c) Force Majeure events; or (d) suspension of the Client's account due to overdue invoices or security violations.
      </p>

      <h3>2. Incident Severity Tiers &amp; Response Times</h3>
      <table>
        <thead>
          <tr>
            <th style="width: 16%;">Severity Level</th>
            <th style="width: 42%;">Definition &amp; Examples</th>
            <th style="width: 21%;">Initial Response Time</th>
            <th style="width: 21%;">Target Resolution / Workaround</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>P1 — Critical</strong></td>
            <td>Complete production Platform outage, multi-tenant login failure, active examination/valuation halt, or confirmed security/data breach.</td>
            <td>&le; 1 Hour (24&times;7)</td>
            <td>&le; 4 Hours</td>
          </tr>
          <tr>
            <td><strong>P2 — High</strong></td>
            <td>Major module failure impairing critical daily workflows (e.g., Face Attendance check-in failing campus-wide, fee payment webhook failure, or bus tracking offline) with no immediate workaround.</td>
            <td>&le; 4 Business Hours</td>
            <td>&le; 12 Business Hours</td>
          </tr>
          <tr>
            <td><strong>P3 — Medium</strong></td>
            <td>Partial feature degradation affecting a single department or non-critical workflow (e.g., report export formatting, single user device lock reset issue) where a workaround exists.</td>
            <td>&le; 1 Business Day</td>
            <td>&le; 3 Business Days</td>
          </tr>
          <tr>
            <td><strong>P4 — Low</strong></td>
            <td>Cosmetic UI issues, general "how-to" inquiries, configuration assistance, or feature enhancement requests.</td>
            <td>&le; 2 Business Days</td>
            <td>Next Scheduled Release</td>
          </tr>
        </tbody>
      </table>
      <p>
        <em>Standard Support Hours:</em> Monday through Saturday, 09:00 AM IST to 07:00 PM IST (excluding gazetted national holidays), with 24&times;7 emergency escalation monitoring for P1 Critical incidents.
      </p>

      <h3>3. Data Backup &amp; Disaster Recovery</h3>
      <ul>
        <li><strong>Automated Backups:</strong> Provider performs automated daily encrypted snapshots of all PostgreSQL tenant schemas and incremental backups of media storage retained for a rolling period of at least thirty (30) days.</li>
        <li><strong>Recovery Point Objective (RPO):</strong> Maximum potential data loss in the event of a catastrophic infrastructure failure shall not exceed <strong>twenty-four (24) hours</strong> (and &le; 1 hour where point-in-time WAL archiving is enabled).</li>
        <li><strong>Recovery Time Objective (RTO):</strong> Service restoration following a disaster event shall be targeted within <strong>six (6) hours</strong>.</li>
      </ul>

      <h3>4. Service Credits for SLA Breach</h3>
      <p>
        If the Monthly Uptime Percentage falls below 99.5% in any calendar month, the Client may request a Service Credit within fifteen (15) days of the end of the affected month, applied against the next renewal invoice:
      </p>
      <table>
        <thead>
          <tr>
            <th>Monthly Uptime Percentage Achieved</th>
            <th>Service Credit (% of Pro-Rated Monthly Subscription Fee)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>99.00% to &lt; 99.50%</td>
            <td>5% Service Credit</td>
          </tr>
          <tr>
            <td>98.00% to &lt; 99.00%</td>
            <td>10% Service Credit</td>
          </tr>
          <tr>
            <td>Below 98.00%</td>
            <td>20% Service Credit</td>
          </tr>
        </tbody>
      </table>
      <p>
        Service Credits represent the Client's sole and exclusive monetary remedy for any failure to meet the Monthly Uptime Commitment, provided that if Monthly Uptime falls below 95.0% for three (3) consecutive months, the Client may terminate this Agreement for cause and receive a pro-rata refund of prepaid unearned subscription fees.
      </p>
    </section>

    <section id="part-5" class="agreement-part page-break">
      <div class="part-banner">
        <span class="part-label">Part V of V</span>
        <h2>End-User Acceptable Use &amp; Terms of Service (EULA)</h2>
      </div>
      <div class="clause-box">
        <strong>Notice to End Users:</strong> These Terms govern all individual users (Students, Faculty, Administrative Staff, Transport Personnel, and Parents/Guardians) accessing the <em>CampusNexus</em> Platform provided by <strong>{tenant_name}</strong>.
      </div>

      <h3>1. Account Registration, Domain Verification &amp; Device Binding</h3>
      <p>
        <strong>1.1 Official Identity:</strong> You must register and access the Platform using only your authentic identity, institutional roll/employee number, and (where mandated by your Institution) your official institutional email address matching the permitted domain (<code>@{permitted_domain}</code>).
      </p>
      <p>
        <strong>1.2 Single-Device Binding &amp; Security:</strong> To prevent academic fraud and proxy attendance, your account may be cryptographically bound to your primary mobile device. You are strictly prohibited from sharing your password, OTPs, or session tokens with any other person. If you change or lose your mobile device, you must submit an official Device Reset Request through the Platform for verification and approval by your Lecturer or Institution Administrator.
      </p>

      <h3>2. Integrity of Biometric, Geolocation &amp; QR Attendance</h3>
      <p>
        By using the Attendance, Classroom Check-In, or Bus Boarding features, you agree that you shall <strong>NOT</strong>:
      </p>
      <ul>
        <li>Attempt to spoof, bypass, or manipulate the camera facial recognition or liveness challenge system using static photographs, pre-recorded videos, deepfakes, masks, or virtual camera injection tools;</li>
        <li>Use GPS-spoofing applications, mock-location developer tools, VPNs, or emulators to falsify your physical presence inside a classroom or campus geofence;</li>
        <li>Share, screenshot, or broadcast time-sensitive Lecture Check-In Codes or Bus Boarding QR Codes to individuals who are not physically present in the classroom or bus; or</li>
        <li>Mark or attempt to mark attendance on behalf of another student or staff member.</li>
      </ul>
      <p>
        <em>Consequences of Violation:</em> Every attendance attempt, liveness check, device mismatch, and location validation is logged with forensic metadata. Any attempt to falsify attendance constitutes a serious breach of institutional discipline and may result in immediate account suspension and disciplinary action by your Institution.
      </p>

      <h3>3. Academic Integrity, Examinations &amp; Submissions</h3>
      <p>
        <strong>3.1 Examination Confidentiality:</strong> Faculty and staff authorized to access Question Banks, Paper Blueprints, Generated Question Paper Sets, and Answer Script Valuation modules must maintain strict examination secrecy and shall not download, photograph, or disclose unreleased examination content.
      </p>
      <p>
        <strong>3.2 Student Submissions:</strong> Assignments, project files, placement resumes, and leave/medical certificates uploaded by Students or Guardians must be authentic, free of malware, and must not infringe third-party intellectual property rights.
      </p>

      <h3>4. Fee Payments &amp; Financial Transactions</h3>
      <p>
        When making online fee payments or uploading offline bank transfer/UTR receipts through the Platform: (a) you warrant that you are authorized to use the selected payment instrument (UPI, NetBanking, Debit/Credit Card, or Wallet); (b) convenience fees or gateway surcharges (if configured by your Institution under <code>pass_to_student</code> mode) will be displayed prior to payment confirmation and are non-refundable once a transaction is processed; and (c) submitting fabricated or altered bank payment receipts or UTR numbers is a punishable offense.
      </p>

      <h3>5. Privacy Consent &amp; Data Principal Rights</h3>
      <p>
        Your Personal Data is processed by the Platform strictly on behalf of your Educational Institution (the Data Fiduciary) in accordance with the <em>Digital Personal Data Protection Act, 2023</em> and Part III of the Master Client Agreement. You (or your Parent/Guardian, if you are under 18 years of age) may view your recorded consents, request corrections to inaccurate profile or attendance records, or exercise your statutory data rights through the Privacy &amp; Consent settings inside your Platform profile or by contacting your Institution's Nodal Grievance Officer.
      </p>
    </section>

    <section id="signatures" class="agreement-part">
      <h3>Execution &amp; Authorized Signatures</h3>
      <p>
        <strong>IN WITNESS WHEREOF</strong>, the Parties have caused this Master Client Agreement (incorporating the Commercial Order Form and Parts I through V) to be executed by their duly authorized representatives as of the Effective Date first written above.
      </p>

      <div class="signature-grid">
        <div class="signature-card">
          <h4>Signed for and on behalf of the Provider</h4>
          <p><strong>Entity:</strong> <span contenteditable="true" class="fill-blank">Polynexus Technologies Private Limited</span></p>
          <div class="sig-line"></div>
          <p style="margin-top: 6px; font-size: 9.5pt;">
            <strong>Authorized Signatory Name:</strong> <span contenteditable="true" class="fill-blank">[Name]</span><br />
            <strong>Designation:</strong> <span contenteditable="true" class="fill-blank">[Director / CEO]</span><br />
            <strong>Date:</strong> <span contenteditable="true" class="fill-blank">{today_str}</span><br />
            <strong>Place:</strong> <span contenteditable="true" class="fill-blank">[City]</span><br />
            <em>(Company Seal / Stamp)</em>
          </p>
        </div>

        <div class="signature-card">
          <h4>Signed for and on behalf of the Client Institution</h4>
          <p><strong>Institution:</strong> <span contenteditable="true" class="fill-blank">{tenant_name}</span></p>
          <div class="sig-line"></div>
          <p style="margin-top: 6px; font-size: 9.5pt;">
            <strong>Authorized Signatory Name:</strong> <span contenteditable="true" class="fill-blank">[Name]</span><br />
            <strong>Designation:</strong> <span contenteditable="true" class="fill-blank">[Principal / Registrar / Trustee / Director]</span><br />
            <strong>Date:</strong> <span contenteditable="true" class="fill-blank">{today_str}</span><br />
            <strong>Place:</strong> <span contenteditable="true" class="fill-blank">[City]</span><br />
            <em>(Institution Official Seal / Stamp)</em>
          </p>
        </div>
      </div>

      <table style="margin-top: 22px;">
        <thead>
          <tr>
            <th style="width: 50%;">Witness 1</th>
            <th style="width: 50%;">Witness 2</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <strong>Signature:</strong> ___________________________<br />
              <strong>Name:</strong> <span contenteditable="true" class="fill-blank">[Witness 1 Name]</span><br />
              <strong>Address / Designation:</strong> <span contenteditable="true" class="fill-blank">[Details]</span>
            </td>
            <td>
              <strong>Signature:</strong> ___________________________<br />
              <strong>Name:</strong> <span contenteditable="true" class="fill-blank">[Witness 2 Name]</span><br />
              <strong>Address / Designation:</strong> <span contenteditable="true" class="fill-blank">[Details]</span>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

  </div>
</body>
</html>
"""

