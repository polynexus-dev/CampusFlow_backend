"""
Payroll Views
==============
Salary structure management, payslip generation linked to attendance + leave data,
and payslip viewing for employees and admins.
"""

import calendar
from decimal import Decimal
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth.models import User
from ..models.payroll import SalaryStructure, Payslip
from ..models.attendance import Attendance
from ..models.leave import LeaveRequest
from ..permissions import (
    IsCollegeAdmin, IsNotStudent,
    get_user_group, is_college_admin
)


class SalaryStructureListView(APIView):
    """
    GET: List all salary structures (Admin only).
    """
    permission_classes = [IsAuthenticated, IsCollegeAdmin]

    def get(self, request):
        structures = SalaryStructure.objects.all().select_related('user')
        data = []
        for s in structures:
            group_name = s.user.groups.first().name if s.user.groups.exists() else "No Role"
            data.append({
                "id": s.id,
                "user_id": s.user.id,
                "username": s.user.username,
                "full_name": s.user.get_full_name(),
                "role": group_name,
                "basic_pay": str(s.basic_pay),
                "hra": str(s.hra),
                "da": str(s.da),
                "ta": str(s.ta),
                "other_allowances": str(s.other_allowances),
                "pf_deduction": str(s.pf_deduction),
                "esi_deduction": str(s.esi_deduction),
                "tds_deduction": str(s.tds_deduction),
                "other_deductions": str(s.other_deductions),
                "gross_salary": str(s.gross_salary),
                "total_deductions": str(s.total_deductions),
                "net_salary": str(s.net_salary),
            })
        return Response(data, status=status.HTTP_200_OK)


class SalaryStructureDetailView(APIView):
    """
    GET: View salary structure for a specific user.
    PUT: Update salary structure (Admin only).
    """
    permission_classes = [IsAuthenticated, IsCollegeAdmin]

    def get(self, request, user_id):
        try:
            target_user = User.objects.exclude(groups__name='student').get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "Employee not found."}, status=status.HTTP_404_NOT_FOUND)

        structure, created = SalaryStructure.objects.get_or_create(user=target_user)
        data = {
            "user_id": target_user.id,
            "username": target_user.username,
            "full_name": target_user.get_full_name(),
            "basic_pay": str(structure.basic_pay),
            "hra": str(structure.hra),
            "da": str(structure.da),
            "ta": str(structure.ta),
            "other_allowances": str(structure.other_allowances),
            "pf_deduction": str(structure.pf_deduction),
            "esi_deduction": str(structure.esi_deduction),
            "tds_deduction": str(structure.tds_deduction),
            "other_deductions": str(structure.other_deductions),
            "gross_salary": str(structure.gross_salary),
            "total_deductions": str(structure.total_deductions),
            "net_salary": str(structure.net_salary),
        }
        return Response(data, status=status.HTTP_200_OK)

    def put(self, request, user_id):
        try:
            target_user = User.objects.exclude(groups__name='student').get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "Employee not found."}, status=status.HTTP_404_NOT_FOUND)

        structure, _ = SalaryStructure.objects.get_or_create(user=target_user)

        fields = ['basic_pay', 'hra', 'da', 'ta', 'other_allowances',
                   'pf_deduction', 'esi_deduction', 'tds_deduction', 'other_deductions']
        for field in fields:
            if field in request.data:
                setattr(structure, field, Decimal(str(request.data[field])))
        structure.save()

        return Response({
            "message": "Salary structure updated.",
            "gross_salary": str(structure.gross_salary),
            "net_salary": str(structure.net_salary),
        }, status=status.HTTP_200_OK)


class GeneratePayslipView(APIView):
    """
    POST: Generate a payslip for a specific employee for a given month/year.
    Calculates present days from Attendance, leave days from LeaveRequest,
    and applies absence deductions.
    """
    permission_classes = [IsAuthenticated, IsCollegeAdmin]

    def post(self, request):
        user_id = request.data.get('user_id')
        month = int(request.data.get('month', 0))
        year = int(request.data.get('year', 0))

        if not user_id or not month or not year:
            return Response({"error": "user_id, month, and year are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            target_user = User.objects.exclude(groups__name='student').get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "Employee not found."}, status=status.HTTP_404_NOT_FOUND)

        # Check if payslip already exists
        if Payslip.objects.filter(user=target_user, month=month, year=year).exists():
            return Response({"error": "Payslip already exists for this period."}, status=status.HTTP_400_BAD_REQUEST)

        # Get salary structure
        try:
            salary = SalaryStructure.objects.get(user=target_user)
        except SalaryStructure.DoesNotExist:
            return Response({"error": "No salary structure found for this employee."}, status=status.HTTP_400_BAD_REQUEST)

        # Calculate working days (weekdays in the month)
        _, days_in_month = calendar.monthrange(year, month)
        import datetime
        total_working_days = sum(
            1 for day in range(1, days_in_month + 1)
            if datetime.date(year, month, day).weekday() < 5  # Mon-Fri
        )

        # Calculate present days from Attendance records
        present_days = Attendance.objects.filter(
            user=target_user,
            check_in_time__year=year,
            check_in_time__month=month,
        ).dates('check_in_time', 'day').count()

        # Calculate approved leave days in this month
        from django.db.models import Q
        leave_days = 0
        approved_leaves = LeaveRequest.objects.filter(
            user=target_user,
            status='approved',
        ).filter(
            Q(start_date__year=year, start_date__month=month) |
            Q(end_date__year=year, end_date__month=month)
        )
        for leave in approved_leaves:
            # Calculate overlap with this month
            month_start = datetime.date(year, month, 1)
            month_end = datetime.date(year, month, days_in_month)
            effective_start = max(leave.start_date, month_start)
            effective_end = min(leave.end_date, month_end)
            if effective_start <= effective_end:
                leave_days += (effective_end - effective_start).days + 1

        # Calculate absent days
        absent_days = max(0, total_working_days - present_days - leave_days)

        # Calculate pay
        gross = salary.gross_salary
        deductions = salary.total_deductions
        per_day = gross / Decimal(total_working_days) if total_working_days > 0 else Decimal(0)
        absence_deduction = per_day * Decimal(absent_days)
        net_payable = gross - deductions - absence_deduction

        payslip = Payslip.objects.create(
            user=target_user,
            month=month,
            year=year,
            total_working_days=total_working_days,
            present_days=present_days,
            leave_days=leave_days,
            absent_days=absent_days,
            gross_salary=gross,
            total_deductions=deductions,
            absence_deduction=absence_deduction,
            net_payable=max(Decimal(0), net_payable),
        )

        return Response({
            "message": "Payslip generated.",
            "id": payslip.id,
            "net_payable": str(payslip.net_payable),
            "absent_days": absent_days,
            "present_days": present_days,
            "leave_days": leave_days,
        }, status=status.HTTP_201_CREATED)


class BulkPayslipGenerationView(APIView):
    """POST: Generate payslips for ALL staff for a given month/year."""
    permission_classes = [IsAuthenticated, IsCollegeAdmin]

    def post(self, request):
        month = int(request.data.get('month', 0))
        year = int(request.data.get('year', 0))

        if not month or not year:
            return Response({"error": "month and year are required."}, status=status.HTTP_400_BAD_REQUEST)

        staff = User.objects.exclude(groups__name='student').exclude(is_superuser=True)
        generated = 0
        skipped = 0
        errors = []

        for user in staff:
            if Payslip.objects.filter(user=user, month=month, year=year).exists():
                skipped += 1
                continue
            if not SalaryStructure.objects.filter(user=user).exists():
                errors.append(f"No salary structure for {user.username}")
                continue

            # Delegate to the generate logic
            try:
                salary = SalaryStructure.objects.get(user=user)
                _, days_in_month = calendar.monthrange(year, month)
                import datetime
                total_working_days = sum(
                    1 for day in range(1, days_in_month + 1)
                    if datetime.date(year, month, day).weekday() < 5
                )
                present_days = Attendance.objects.filter(
                    user=user, check_in_time__year=year, check_in_time__month=month,
                ).dates('check_in_time', 'day').count()

                from django.db.models import Q
                leave_days = 0
                for leave in LeaveRequest.objects.filter(user=user, status='approved').filter(
                    Q(start_date__year=year, start_date__month=month) |
                    Q(end_date__year=year, end_date__month=month)
                ):
                    month_start = datetime.date(year, month, 1)
                    month_end = datetime.date(year, month, days_in_month)
                    effective_start = max(leave.start_date, month_start)
                    effective_end = min(leave.end_date, month_end)
                    if effective_start <= effective_end:
                        leave_days += (effective_end - effective_start).days + 1

                absent_days = max(0, total_working_days - present_days - leave_days)
                gross = salary.gross_salary
                deductions = salary.total_deductions
                per_day = gross / Decimal(total_working_days) if total_working_days > 0 else Decimal(0)
                absence_deduction = per_day * Decimal(absent_days)
                net_payable = max(Decimal(0), gross - deductions - absence_deduction)

                Payslip.objects.create(
                    user=user, month=month, year=year,
                    total_working_days=total_working_days, present_days=present_days,
                    leave_days=leave_days, absent_days=absent_days,
                    gross_salary=gross, total_deductions=deductions,
                    absence_deduction=absence_deduction, net_payable=net_payable,
                )
                generated += 1
            except Exception as e:
                errors.append(f"Error for {user.username}: {str(e)}")

        return Response({
            "message": f"Bulk generation complete. Generated: {generated}, Skipped: {skipped}.",
            "generated": generated,
            "skipped": skipped,
            "errors": errors,
        }, status=status.HTTP_200_OK)


class PayslipListView(APIView):
    """
    GET: List payslips.
    - Admin: All payslips (filterable by month/year/user).
    - Employee: Own payslips only.
    """
    permission_classes = [IsAuthenticated, IsNotStudent]

    def get(self, request):
        user = request.user

        if is_college_admin(user):
            qs = Payslip.objects.all()
            target_user_id = request.query_params.get('user_id')
            if target_user_id:
                qs = qs.filter(user_id=target_user_id)
        else:
            qs = Payslip.objects.filter(user=user)

        month = request.query_params.get('month')
        year = request.query_params.get('year')
        if month:
            qs = qs.filter(month=int(month))
        if year:
            qs = qs.filter(year=int(year))

        data = []
        for p in qs.select_related('user'):
            data.append({
                "id": p.id,
                "user_id": p.user.id,
                "username": p.user.username,
                "full_name": p.user.get_full_name(),
                "month": p.month,
                "year": p.year,
                "total_working_days": p.total_working_days,
                "present_days": p.present_days,
                "leave_days": p.leave_days,
                "absent_days": p.absent_days,
                "gross_salary": str(p.gross_salary),
                "total_deductions": str(p.total_deductions),
                "absence_deduction": str(p.absence_deduction),
                "net_payable": str(p.net_payable),
                "status": p.status,
                "generated_on": p.generated_on.isoformat(),
            })
        return Response(data, status=status.HTTP_200_OK)
