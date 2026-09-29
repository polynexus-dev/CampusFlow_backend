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
from django.db import transaction
from django.utils import timezone
from ..models.leave import LeaveType, LeaveBalance, LeaveRequest
from ..permissions import (
    IsCollegeAdmin, IsNotStudent, RequiresModule, PRINCIPAL_ROLE,
    get_user_group, is_saas_admin, is_college_admin, is_principal
)

LEAVE_ADMIN_PERMS = [IsAuthenticated, IsCollegeAdmin, RequiresModule("leave")]
LEAVE_STAFF_PERMS = [IsAuthenticated, IsNotStudent, RequiresModule("leave")]


# ─────────────────────────────────────────────────────────────
# Approval routing
#   Faculty / staff leave → their HOD (College Admins can also act)
#   HOD leave             → the Principal only
#                           (College Admins act only if the college has no
#                            active Principal, so requests never get stuck)
#   Principal leave       → College Admins
#   Nobody can act on their own request.
# ─────────────────────────────────────────────────────────────

def _department_staff_ids(hod_user):
    """User ids of the teaching + non-teaching staff in this HOD's department."""
    hod_profile = getattr(hod_user, 'department_head_profile', None)
    if not hod_profile or not hod_profile.department:
        return set()
    from ..models.profile import TeachingStaffProfile, NonTeachingStaffProfile
    ids = set(TeachingStaffProfile.objects.filter(department=hod_profile.department).values_list('user_id', flat=True))
    ids |= set(NonTeachingStaffProfile.objects.filter(department=hod_profile.department).values_list('user_id', flat=True))
    return ids


def _college_has_active_principal():
    from ..models.profile import PrincipalProfile
    return PrincipalProfile.objects.filter(
        status='active', user__is_active=True, user__groups__name=PRINCIPAL_ROLE
    ).exists()


def _can_act_on(user, leave_req, requester_group, has_principal, dept_staff_ids):
    """Whether `user` may approve/reject `leave_req` under the routing above."""
    if leave_req.user_id == user.id:
        return False
    is_admin = is_college_admin(user) or is_saas_admin(user)
    if requester_group == 'Department Head':
        return is_principal(user) or (is_admin and not has_principal)
    if is_admin:
        return True
    return get_user_group(user) == 'Department Head' and leave_req.user_id in dept_staff_ids


# ─────────────────────────────────────────────────────────────
# Leave Type Configuration (Admin only)
# ─────────────────────────────────────────────────────────────

class LeaveTypeListCreateView(APIView):
    """
    GET: List all leave types.
    POST: Create a new leave type (College Admin only).
    """
    permission_classes = LEAVE_ADMIN_PERMS

    def get_permissions(self):
        # Staff need to read leave types to apply for leave; only admins create them
        if self.request.method == 'GET':
            return [perm() if isinstance(perm, type) else perm for perm in LEAVE_STAFF_PERMS]
        return super().get_permissions()

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
    permission_classes = LEAVE_ADMIN_PERMS

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
    permission_classes = LEAVE_STAFF_PERMS

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
    permission_classes = LEAVE_STAFF_PERMS

    def post(self, request):
        leave_type_id = request.data.get('leave_type_id')
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')
        reason = request.data.get('reason', '').strip()

        if not leave_type_id or not start_date or not end_date or not reason:
            return Response({"error": "leave_type_id, start_date, end_date, and reason are required."}, status=status.HTTP_400_BAD_REQUEST)

        from datetime import datetime
        try:
            parsed_start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            parsed_end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)

        if parsed_start_date > parsed_end_date:
            return Response({"error": "Start date cannot be after end date."}, status=status.HTTP_400_BAD_REQUEST)

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
            start_date=parsed_start_date,
            end_date=parsed_end_date,
            reason=reason,
        )
        return Response(
            {"message": "Leave request submitted.", "id": leave_req.id, "num_days": leave_req.num_days},
            status=status.HTTP_201_CREATED
        )


class LeaveRequestListView(APIView):
    """
    GET: List leave requests.
    - Admin: All requests (oversight), even ones only the Principal can decide.
    - Principal: Requests from Department Heads.
    - HOD: Requests from their department.
    - Others: Their own requests.
    Each item carries `can_act` — whether the caller may approve/reject it.
    """
    permission_classes = LEAVE_STAFF_PERMS

    def get(self, request):
        user = request.user
        user_group = get_user_group(user)
        status_filter = request.query_params.get('status')
        dept_staff_ids = _department_staff_ids(user) if user_group == 'Department Head' else set()

        if is_college_admin(user) or is_saas_admin(user):
            qs = LeaveRequest.objects.all()
        elif user_group == PRINCIPAL_ROLE:
            qs = LeaveRequest.objects.filter(user__groups__name='Department Head')
        elif user_group == 'Department Head' and dept_staff_ids:
            qs = LeaveRequest.objects.filter(user_id__in=dept_staff_ids)
        else:
            qs = LeaveRequest.objects.filter(user=user)

        if status_filter:
            qs = qs.filter(status=status_filter)

        has_principal = _college_has_active_principal()
        data = []
        for lr in qs.select_related('user', 'leave_type', 'approved_by').prefetch_related('user__groups'):
            requester_groups = list(lr.user.groups.all())
            requester_group = requester_groups[0].name if requester_groups else None
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
                "requester_role": requester_group,
                "can_act": lr.status == 'pending' and _can_act_on(
                    user, lr, requester_group, has_principal, dept_staff_ids
                ),
            })
        return Response(data, status=status.HTTP_200_OK)


class LeaveRequestActionView(APIView):
    """
    POST: Approve or reject a leave request, following the routing rules at
    the top of this module (HOD leave → Principal; staff leave → their HOD
    or a College Admin; never your own request).
    """
    permission_classes = LEAVE_STAFF_PERMS

    def post(self, request):
        leave_id = request.data.get('leave_id')
        action = request.data.get('action')  # 'approve' or 'reject'
        rejection_reason = request.data.get('rejection_reason', '')

        if not leave_id or action not in ('approve', 'reject'):
            return Response(
                {"error": "leave_id and action ('approve' or 'reject') are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Row lock: if two approvers act at the same moment, the second waits,
        # then finds the request no longer pending — so the leave balance is
        # only charged once.
        with transaction.atomic():
            try:
                leave_req = LeaveRequest.objects.select_for_update().get(id=leave_id, status='pending')
            except LeaveRequest.DoesNotExist:
                return Response({"error": "Pending leave request not found. It may already have been decided."}, status=status.HTTP_404_NOT_FOUND)

            user = request.user
            requester_group = get_user_group(leave_req.user)
            dept_staff_ids = _department_staff_ids(user) if get_user_group(user) == 'Department Head' else set()

            if not _can_act_on(user, leave_req, requester_group, _college_has_active_principal(), dept_staff_ids):
                if leave_req.user_id == user.id:
                    error = "You cannot approve or reject your own leave request."
                elif requester_group == 'Department Head':
                    error = "Leave requests from a Head of Department are decided by the Principal."
                else:
                    error = "You are not authorized to act on this leave request."
                return Response({"error": error}, status=status.HTTP_403_FORBIDDEN)

            return self._decide(leave_req, user, action, rejection_reason)

    def _decide(self, leave_req, user, action, rejection_reason):
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
    permission_classes = LEAVE_STAFF_PERMS

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
