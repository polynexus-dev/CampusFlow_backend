"""
Leave Management Views
========================
Full leave lifecycle: configure leave types → allocate balances →
submit requests → approve/reject → track history.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone
from ..models.leave import LeaveType, LeaveBalance, LeaveRequest
from ..permissions import (
    IsCollegeAdmin, IsNotStudent,
    get_user_group, is_saas_admin, is_college_admin
)


# ─────────────────────────────────────────────────────────────
# Leave Type Configuration (Admin only)
# ─────────────────────────────────────────────────────────────

class LeaveTypeListCreateView(APIView):
    """
    GET: List all leave types.
    POST: Create a new leave type (College Admin only).
    """
    permission_classes = [IsAuthenticated, IsCollegeAdmin]

    def get(self, request):
        leave_types = LeaveType.objects.filter(is_active=True)
        data = []
        for lt in leave_types:
            data.append({
                "id": lt.id,
                "name": lt.name,
                "code": lt.code,
                "max_days": lt.max_days,
                "is_paid": lt.is_paid,
                "applicable_to": lt.applicable_to,
                "carry_forward": lt.carry_forward,
                "description": lt.description,
            })
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        name = request.data.get('name', '').strip()
        code = request.data.get('code', '').strip().upper()
        max_days = request.data.get('max_days', 12)
        is_paid = request.data.get('is_paid', True)
        applicable_to = request.data.get('applicable_to', [])
        carry_forward = request.data.get('carry_forward', False)
        description = request.data.get('description', '')

        if not name or not code:
            return Response({"error": "Name and code are required."}, status=status.HTTP_400_BAD_REQUEST)

        if LeaveType.objects.filter(code=code).exists():
            return Response({"error": f"Leave type with code '{code}' already exists."}, status=status.HTTP_400_BAD_REQUEST)

        lt = LeaveType.objects.create(
            name=name, code=code, max_days=max_days, is_paid=is_paid,
            applicable_to=applicable_to, carry_forward=carry_forward, description=description
        )
        return Response({"message": "Leave type created.", "id": lt.id}, status=status.HTTP_201_CREATED)


class LeaveTypeDetailView(APIView):
    """PUT/DELETE a leave type (College Admin only)."""
    permission_classes = [IsAuthenticated, IsCollegeAdmin]

    def put(self, request, pk):
        try:
            lt = LeaveType.objects.get(id=pk)
        except LeaveType.DoesNotExist:
            return Response({"error": "Leave type not found."}, status=status.HTTP_404_NOT_FOUND)

        lt.name = request.data.get('name', lt.name)
        lt.code = request.data.get('code', lt.code)
        lt.max_days = request.data.get('max_days', lt.max_days)
        lt.is_paid = request.data.get('is_paid', lt.is_paid)
        lt.applicable_to = request.data.get('applicable_to', lt.applicable_to)
        lt.carry_forward = request.data.get('carry_forward', lt.carry_forward)
        lt.description = request.data.get('description', lt.description)
        lt.save()
        return Response({"message": "Leave type updated."}, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        try:
            lt = LeaveType.objects.get(id=pk)
        except LeaveType.DoesNotExist:
            return Response({"error": "Leave type not found."}, status=status.HTTP_404_NOT_FOUND)
        lt.is_active = False
        lt.save()
        return Response({"message": "Leave type deactivated."}, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────────
# Leave Balance
# ─────────────────────────────────────────────────────────────

class LeaveBalanceView(APIView):
    """
    GET: View leave balances.
    - Staff sees their own balance.
    - Admin sees all or a specific user's balance (?user_id=X).
    POST: Allocate balances for a user (Admin only).
    """
    permission_classes = [IsAuthenticated, IsNotStudent]

    def get(self, request):
        user = request.user
        target_user_id = request.query_params.get('user_id')

        if target_user_id and is_college_admin(user):
            from django.contrib.auth.models import User
            try:
                target_user = User.objects.get(id=target_user_id)
            except User.DoesNotExist:
                return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
            balances = LeaveBalance.objects.filter(user=target_user)
        elif is_college_admin(user):
            # Admin can see all balances
            balances = LeaveBalance.objects.all().select_related('user', 'leave_type')
        else:
            balances = LeaveBalance.objects.filter(user=user)

        data = []
        for bal in balances.select_related('leave_type', 'user'):
            data.append({
                "id": bal.id,
                "user_id": bal.user.id,
                "username": bal.user.username,
                "full_name": bal.user.get_full_name(),
                "leave_type": bal.leave_type.name,
                "leave_code": bal.leave_type.code,
                "academic_year": bal.academic_year,
                "allocated": bal.allocated,
                "used": bal.used,
                "carried": bal.carried,
                "remaining": bal.remaining,
            })
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        """Allocate leave balance for a user (Admin only)."""
        if not is_college_admin(request.user):
            return Response({"error": "Only College Admin can allocate leave."}, status=status.HTTP_403_FORBIDDEN)

        user_id = request.data.get('user_id')
        leave_type_id = request.data.get('leave_type_id')
        academic_year = request.data.get('academic_year', '')
        allocated = request.data.get('allocated', 0)

        if not user_id or not leave_type_id or not academic_year:
            return Response({"error": "user_id, leave_type_id, and academic_year are required."}, status=status.HTTP_400_BAD_REQUEST)

        from django.contrib.auth.models import User
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            leave_type = LeaveType.objects.get(id=leave_type_id)
        except LeaveType.DoesNotExist:
            return Response({"error": "Leave type not found."}, status=status.HTTP_404_NOT_FOUND)

        bal, created = LeaveBalance.objects.get_or_create(
            user=target_user, leave_type=leave_type, academic_year=academic_year,
            defaults={'allocated': allocated}
        )
        if not created:
            bal.allocated = allocated
            bal.save()

        return Response({"message": "Leave balance allocated.", "remaining": bal.remaining}, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────────
# Leave Requests
# ─────────────────────────────────────────────────────────────

class LeaveRequestCreateView(APIView):
    """POST: Submit a new leave request (any non-student staff)."""
    permission_classes = [IsAuthenticated, IsNotStudent]

    def post(self, request):
        leave_type_id = request.data.get('leave_type_id')
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')
        reason = request.data.get('reason', '').strip()

        if not leave_type_id or not start_date or not end_date or not reason:
            return Response({"error": "leave_type_id, start_date, end_date, and reason are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            leave_type = LeaveType.objects.get(id=leave_type_id, is_active=True)
        except LeaveType.DoesNotExist:
            return Response({"error": "Leave type not found."}, status=status.HTTP_404_NOT_FOUND)

        # Check if the user's role is applicable
        user_group = get_user_group(request.user)
        if leave_type.applicable_to and user_group not in leave_type.applicable_to:
            return Response(
                {"error": f"This leave type is not available for your role ({user_group})."},
                status=status.HTTP_403_FORBIDDEN
            )

        leave_req = LeaveRequest.objects.create(
            user=request.user,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
        )
        return Response(
            {"message": "Leave request submitted.", "id": leave_req.id, "num_days": leave_req.num_days},
            status=status.HTTP_201_CREATED
        )


class LeaveRequestListView(APIView):
    """
    GET: List leave requests.
    - Admin: All pending/approved/rejected requests.
    - HOD: Requests from their department.
    - Others: Their own requests.
    """
    permission_classes = [IsAuthenticated, IsNotStudent]

    def get(self, request):
        user = request.user
        user_group = get_user_group(user)
        status_filter = request.query_params.get('status')

        if is_college_admin(user) or is_saas_admin(user):
            qs = LeaveRequest.objects.all()
        elif user_group == 'Department Head':
            # HOD sees requests from their department
            hod_profile = getattr(user, 'department_head_profile', None)
            if hod_profile and hod_profile.department:
                from ..models.profile import TeachingStaffProfile, NonTeachingStaffProfile
                dept_user_ids = set()
                for p in TeachingStaffProfile.objects.filter(department=hod_profile.department):
                    dept_user_ids.add(p.user_id)
                for p in NonTeachingStaffProfile.objects.filter(department=hod_profile.department):
                    dept_user_ids.add(p.user_id)
                qs = LeaveRequest.objects.filter(user_id__in=dept_user_ids)
            else:
                qs = LeaveRequest.objects.filter(user=user)
        else:
            qs = LeaveRequest.objects.filter(user=user)

        if status_filter:
            qs = qs.filter(status=status_filter)

        data = []
        for lr in qs.select_related('user', 'leave_type', 'approved_by'):
            data.append({
                "id": lr.id,
                "user_id": lr.user.id,
                "username": lr.user.username,
                "full_name": lr.user.get_full_name(),
                "leave_type": lr.leave_type.name,
                "leave_code": lr.leave_type.code,
                "start_date": str(lr.start_date),
                "end_date": str(lr.end_date),
                "num_days": lr.num_days,
                "reason": lr.reason,
                "status": lr.status,
                "approved_by": lr.approved_by.get_full_name() if lr.approved_by else None,
                "rejection_reason": lr.rejection_reason,
                "applied_on": lr.applied_on.isoformat(),
                "reviewed_on": lr.reviewed_on.isoformat() if lr.reviewed_on else None,
            })
        return Response(data, status=status.HTTP_200_OK)


class LeaveRequestActionView(APIView):
    """
    POST: Approve or reject a leave request.
    - Admin can approve/reject any request.
    - HOD can approve/reject requests from their department.
    """
    permission_classes = [IsAuthenticated, IsNotStudent]

    def post(self, request):
        leave_id = request.data.get('leave_id')
        action = request.data.get('action')  # 'approve' or 'reject'
        rejection_reason = request.data.get('rejection_reason', '')

        if not leave_id or action not in ('approve', 'reject'):
            return Response(
                {"error": "leave_id and action ('approve' or 'reject') are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            leave_req = LeaveRequest.objects.get(id=leave_id, status='pending')
        except LeaveRequest.DoesNotExist:
            return Response({"error": "Pending leave request not found."}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        user_group = get_user_group(user)

        # Authorization check
        authorized = False
        if is_college_admin(user) or is_saas_admin(user):
            authorized = True
        elif user_group == 'Department Head':
            hod_profile = getattr(user, 'department_head_profile', None)
            if hod_profile and hod_profile.department:
                from ..models.profile import TeachingStaffProfile, NonTeachingStaffProfile
                dept_user_ids = set()
                for p in TeachingStaffProfile.objects.filter(department=hod_profile.department):
                    dept_user_ids.add(p.user_id)
                for p in NonTeachingStaffProfile.objects.filter(department=hod_profile.department):
                    dept_user_ids.add(p.user_id)
                if leave_req.user_id in dept_user_ids:
                    authorized = True

        if not authorized:
            return Response({"error": "You are not authorized to act on this leave request."}, status=status.HTTP_403_FORBIDDEN)

        if action == 'approve':
            leave_req.status = 'approved'
            leave_req.approved_by = user
            leave_req.reviewed_on = timezone.now()
            leave_req.save()

            # Update leave balance
            from datetime import datetime
            academic_year = f"{leave_req.start_date.year}-{leave_req.start_date.year + 1}"
            bal, _ = LeaveBalance.objects.get_or_create(
                user=leave_req.user,
                leave_type=leave_req.leave_type,
                academic_year=academic_year,
                defaults={'allocated': leave_req.leave_type.max_days}
            )
            bal.used += leave_req.num_days
            bal.save()

            msg = f"Leave request approved for {leave_req.user.get_full_name()}."
        else:
            leave_req.status = 'rejected'
            leave_req.approved_by = user
            leave_req.rejection_reason = rejection_reason
            leave_req.reviewed_on = timezone.now()
            leave_req.save()
            msg = f"Leave request rejected for {leave_req.user.get_full_name()}."

        return Response({"message": msg, "status": leave_req.status}, status=status.HTTP_200_OK)


class MyLeavesView(APIView):
    """GET: View own leave history and balances (any non-student)."""
    permission_classes = [IsAuthenticated, IsNotStudent]

    def get(self, request):
        user = request.user

        # Balances
        balances = LeaveBalance.objects.filter(user=user).select_related('leave_type')
        balance_data = []
        for bal in balances:
            balance_data.append({
                "leave_type": bal.leave_type.name,
                "leave_code": bal.leave_type.code,
                "academic_year": bal.academic_year,
                "allocated": bal.allocated,
                "used": bal.used,
                "carried": bal.carried,
                "remaining": bal.remaining,
            })

        # Requests
        requests = LeaveRequest.objects.filter(user=user).select_related('leave_type', 'approved_by')
        request_data = []
        for lr in requests:
            request_data.append({
                "id": lr.id,
                "leave_type": lr.leave_type.name,
                "leave_code": lr.leave_type.code,
                "start_date": str(lr.start_date),
                "end_date": str(lr.end_date),
                "num_days": lr.num_days,
                "reason": lr.reason,
                "status": lr.status,
                "approved_by": lr.approved_by.get_full_name() if lr.approved_by else None,
                "applied_on": lr.applied_on.isoformat(),
            })

        return Response({
            "balances": balance_data,
            "requests": request_data,
        }, status=status.HTTP_200_OK)
