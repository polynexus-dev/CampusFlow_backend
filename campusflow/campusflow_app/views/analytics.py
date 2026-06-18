"""
Analytics Views
================
Aggregated data endpoints for charts and KPI cards.
Provides attendance trends, department performance, leave analytics,
payroll summaries, and staff attendance breakdowns.
"""

import datetime
from collections import defaultdict
from decimal import Decimal
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Count, Avg, Sum, Q
from django.contrib.auth.models import User
from ..models.attendance import Attendance
from ..models.leave import LeaveRequest
from ..models.payroll import Payslip
from ..models.department import Department
from ..models.profile import (
    StudentProfile, TeachingStaffProfile, NonTeachingStaffProfile,
    ManagementProfile, AdministratorProfile, DepartmentHeadProfile
)
from ..permissions import IsCollegeAdmin, IsFacultyOrAbove, get_user_group, is_college_admin


class OverviewKPIView(APIView):
    """GET: High-level KPI stats for dashboard cards."""
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def get(self, request):
        total_students = StudentProfile.objects.count()
        total_staff = (
            TeachingStaffProfile.objects.count() +
            NonTeachingStaffProfile.objects.count() +
            ManagementProfile.objects.count() +
            AdministratorProfile.objects.count() +
            DepartmentHeadProfile.objects.count()
        )
        total_departments = Department.objects.count()
        pending_leaves = LeaveRequest.objects.filter(status='pending').count()

        # Today's attendance
        today = datetime.date.today()
        todays_attendance = Attendance.objects.filter(
            check_in_time__date=today
        ).values('user').distinct().count()

        # This month's payroll total
        current_month = today.month
        current_year = today.year
        payroll_total = Payslip.objects.filter(
            month=current_month, year=current_year
        ).aggregate(total=Sum('net_payable'))['total'] or Decimal(0)

        return Response({
            "total_students": total_students,
            "total_staff": total_staff,
            "total_departments": total_departments,
            "pending_leaves": pending_leaves,
            "todays_attendance": todays_attendance,
            "monthly_payroll_total": str(payroll_total),
        }, status=status.HTTP_200_OK)


class AttendanceTrendsView(APIView):
    """
    GET: Attendance count per day over a date range.
    Query params: ?days=30 (default), ?department_id=X
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def get(self, request):
        days = int(request.query_params.get('days', 30))
        department_id = request.query_params.get('department_id')
        end_date = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=days)

        qs = Attendance.objects.filter(
            check_in_time__date__gte=start_date,
            check_in_time__date__lte=end_date,
        )

        # If department filter, get user IDs in that department
        if department_id:
            dept_user_ids = set()
            for model in [StudentProfile, TeachingStaffProfile, NonTeachingStaffProfile]:
                for p in model.objects.filter(department_id=department_id):
                    dept_user_ids.add(p.user_id)
            qs = qs.filter(user_id__in=dept_user_ids)

        # Group by date
        daily_counts = (
            qs.values('check_in_time__date')
            .annotate(count=Count('id'))
            .order_by('check_in_time__date')
        )

        data = []
        for entry in daily_counts:
            data.append({
                "date": str(entry['check_in_time__date']),
                "count": entry['count'],
            })

        return Response(data, status=status.HTTP_200_OK)


class DepartmentPerformanceView(APIView):
    """
    GET: Department-wise summary — student count, staff count, avg attendance.
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def get(self, request):
        departments = Department.objects.all()
        data = []

        for dept in departments:
            student_count = StudentProfile.objects.filter(department=dept).count()
            staff_count = (
                TeachingStaffProfile.objects.filter(department=dept).count() +
                NonTeachingStaffProfile.objects.filter(department=dept).count()
            )

            # Get all user IDs in this department
            dept_user_ids = set()
            for p in StudentProfile.objects.filter(department=dept):
                dept_user_ids.add(p.user_id)
            for p in TeachingStaffProfile.objects.filter(department=dept):
                dept_user_ids.add(p.user_id)
            for p in NonTeachingStaffProfile.objects.filter(department=dept):
                dept_user_ids.add(p.user_id)

            # Count attendance records in last 30 days
            thirty_days_ago = datetime.date.today() - datetime.timedelta(days=30)
            attendance_count = Attendance.objects.filter(
                user_id__in=dept_user_ids,
                check_in_time__date__gte=thirty_days_ago,
            ).count()

            data.append({
                "id": dept.id,
                "name": dept.name,
                "code": dept.code,
                "student_count": student_count,
                "staff_count": staff_count,
                "total_members": student_count + staff_count,
                "attendance_30d": attendance_count,
            })

        return Response(data, status=status.HTTP_200_OK)


class LeaveAnalyticsView(APIView):
    """GET: Leave type distribution and trends."""
    permission_classes = [IsAuthenticated, IsCollegeAdmin]

    def get(self, request):
        # Leave type distribution (count of approved leaves by type)
        type_distribution = (
            LeaveRequest.objects.filter(status='approved')
            .values('leave_type__name', 'leave_type__code')
            .annotate(count=Count('id'), total_days=Sum('id'))
            .order_by('-count')
        )

        # Calculate actual total days for each type
        type_data = []
        for entry in type_distribution:
            # Sum actual days
            leaves = LeaveRequest.objects.filter(
                status='approved',
                leave_type__code=entry['leave_type__code']
            )
            total_days = sum(lr.num_days for lr in leaves)
            type_data.append({
                "leave_type": entry['leave_type__name'],
                "code": entry['leave_type__code'],
                "count": entry['count'],
                "total_days": total_days,
            })

        # Monthly leave trend (last 6 months)
        monthly_trend = []
        today = datetime.date.today()
        for i in range(5, -1, -1):
            month = today.month - i
            year = today.year
            if month <= 0:
                month += 12
                year -= 1
            count = LeaveRequest.objects.filter(
                status='approved',
                start_date__year=year,
                start_date__month=month,
            ).count()
            monthly_trend.append({
                "month": f"{year}-{month:02d}",
                "count": count,
            })

        return Response({
            "type_distribution": type_data,
            "monthly_trend": monthly_trend,
        }, status=status.HTTP_200_OK)


class PayrollSummaryView(APIView):
    """GET: Monthly payroll breakdown totals."""
    permission_classes = [IsAuthenticated, IsCollegeAdmin]

    def get(self, request):
        year = int(request.query_params.get('year', datetime.date.today().year))

        monthly_data = []
        for month in range(1, 13):
            payslips = Payslip.objects.filter(month=month, year=year)
            if payslips.exists():
                agg = payslips.aggregate(
                    total_gross=Sum('gross_salary'),
                    total_deductions=Sum('total_deductions'),
                    total_absence=Sum('absence_deduction'),
                    total_net=Sum('net_payable'),
                    count=Count('id'),
                )
                monthly_data.append({
                    "month": month,
                    "year": year,
                    "employee_count": agg['count'],
                    "total_gross": str(agg['total_gross'] or 0),
                    "total_deductions": str(agg['total_deductions'] or 0),
                    "total_absence_deduction": str(agg['total_absence'] or 0),
                    "total_net_payable": str(agg['total_net'] or 0),
                })
            else:
                monthly_data.append({
                    "month": month,
                    "year": year,
                    "employee_count": 0,
                    "total_gross": "0",
                    "total_deductions": "0",
                    "total_absence_deduction": "0",
                    "total_net_payable": "0",
                })

        return Response(monthly_data, status=status.HTTP_200_OK)
