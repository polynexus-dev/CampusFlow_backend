from rest_framework import viewsets, status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework import serializers as drf_serializers
from django.db import IntegrityError, transaction
from django.db.models import Sum, Q
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal

from campusflow_app.models import (
    FeeCategory, FeeStructure, FeeStructureItem,
    StudentFeeInvoice, StudentFeeInvoiceItem, FeePayment
)
from campusflow_app.models.academics import Batch, Program
from campusflow_app.models.profile import StudentProfile
from campusflow_app.permissions import IsSaaSOrCollegeAdmin, IsNotStudent, RequiresModule
from campusflow_app.services.academic_roster import resolve_student_roster

User = get_user_model()

FEES_PERMS = [IsAuthenticated, RequiresModule("fees")]
FEES_ADMIN_PERMS = [IsAuthenticated, IsSaaSOrCollegeAdmin, RequiresModule("fees")]


# ─────────────────────────────────────────────────────────────────────────────
# Serializers
# ─────────────────────────────────────────────────────────────────────────────

class FeeCategorySerializer(drf_serializers.ModelSerializer):
    class Meta:
        model = FeeCategory
        fields = "__all__"


class FeeStructureItemSerializer(drf_serializers.ModelSerializer):
    category_name = drf_serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = FeeStructureItem
        fields = ["id", "category", "category_name", "amount"]


class FeeStructureSerializer(drf_serializers.ModelSerializer):
    items = FeeStructureItemSerializer(many=True, required=False)
    department_name = drf_serializers.CharField(source="department.name", read_only=True)
    # Structured targeting, alongside the three legacy CharFields below — see
    # models/fees.py for why both forms coexist. Exposed here so an admin can
    # actually set them; without this the FK columns from the curriculum PR
    # were only reachable from the Django shell.
    program_name = drf_serializers.CharField(source="program.short_name", read_only=True, default=None)
    batch_name = drf_serializers.CharField(source="batch.name", read_only=True, default=None)
    academic_year_ref_name = drf_serializers.CharField(source="academic_year_ref.name", read_only=True, default=None)
    total_amount = drf_serializers.SerializerMethodField()

    class Meta:
        model = FeeStructure
        fields = [
            "id", "name", "department", "department_name",
            "batch_academic_year", "program_enrolled_in",
            "current_semester_year", "items", "total_amount",
            "program", "program_name", "batch", "batch_name",
            "semester_number", "academic_year_ref", "academic_year_ref_name",
            "created_at", "updated_at"
        ]

    def get_total_amount(self, obj):
        return sum(item.amount for item in obj.items.all())

    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop('items', None)
        items_data = self.context['request'].data.get('items', [])
        structure = FeeStructure.objects.create(**validated_data)
        for item_data in items_data:
            FeeStructureItem.objects.create(
                fee_structure=structure,
                category_id=item_data['category'],
                amount=Decimal(str(item_data['amount']))
            )
        return structure

    @transaction.atomic
    def update(self, instance, validated_data):
        validated_data.pop('items', None)
        items_data = self.context['request'].data.get('items', None)
        instance.name = validated_data.get('name', instance.name)
        instance.department = validated_data.get('department', instance.department)
        instance.batch_academic_year = validated_data.get('batch_academic_year', instance.batch_academic_year)
        instance.program_enrolled_in = validated_data.get('program_enrolled_in', instance.program_enrolled_in)
        instance.current_semester_year = validated_data.get('current_semester_year', instance.current_semester_year)
        instance.program = validated_data.get('program', instance.program)
        instance.batch = validated_data.get('batch', instance.batch)
        instance.semester_number = validated_data.get('semester_number', instance.semester_number)
        instance.academic_year_ref = validated_data.get('academic_year_ref', instance.academic_year_ref)
        instance.save()

        if items_data is not None:
            # Recreate items simply to avoid diff complications
            instance.items.all().delete()
            for item_data in items_data:
                FeeStructureItem.objects.create(
                    fee_structure=instance,
                    category_id=item_data['category'],
                    amount=Decimal(str(item_data['amount']))
                )
        return instance


class StudentFeeInvoiceItemSerializer(drf_serializers.ModelSerializer):
    category_name = drf_serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = StudentFeeInvoiceItem
        fields = ["id", "category", "category_name", "amount"]


class StudentFeeInvoiceSerializer(drf_serializers.ModelSerializer):
    items = StudentFeeInvoiceItemSerializer(many=True, read_only=True)
    student_name = drf_serializers.SerializerMethodField()
    remaining_balance = drf_serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = StudentFeeInvoice
        fields = [
            "id", "student", "student_name", "fee_structure",
            "invoice_number", "due_date", "total_amount",
            "discount_amount", "paid_amount", "remaining_balance",
            "status", "items", "created_at", "updated_at"
        ]

    def get_student_name(self, obj):
        return obj.student.get_full_name() or obj.student.username


class FeePaymentSerializer(drf_serializers.ModelSerializer):
    student_name = drf_serializers.SerializerMethodField()
    invoice_number = drf_serializers.CharField(source="invoice.invoice_number", read_only=True)

    class Meta:
        model = FeePayment
        fields = [
            "id", "invoice", "invoice_number", "amount_paid",
            "payment_method", "transaction_reference",
            "receipt_number", "payment_date", "remarks",
            "collected_by", "student_name"
        ]
        read_only_fields = ["receipt_number", "payment_date", "collected_by"]

    def get_student_name(self, obj):
        return obj.invoice.student.get_full_name() or obj.invoice.student.username


# ─────────────────────────────────────────────────────────────────────────────
# ViewSets & Views
# ─────────────────────────────────────────────────────────────────────────────

class FeeCategoryViewSet(viewsets.ModelViewSet):
    """
    CRUD fee categories. Only admins can create/update/delete.
    Any authenticated user (faculty/students) can list.
    """
    queryset = FeeCategory.objects.all().order_by("name")
    serializer_class = FeeCategorySerializer
    permission_classes = FEES_PERMS

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsAuthenticated(), IsSaaSOrCollegeAdmin(), RequiresModule("fees")()]
        return super().get_permissions()


class FeeStructureViewSet(viewsets.ModelViewSet):
    """
    CRUD fee structure templates. Only admins.
    """
    queryset = FeeStructure.objects.all().prefetch_related("items__category", "department").order_by("-created_at")
    serializer_class = FeeStructureSerializer
    permission_classes = FEES_ADMIN_PERMS


class StudentFeeInvoiceViewSet(viewsets.ModelViewSet):
    """
    Manage student invoices.
    Admins can see all, students can only see their own.
    """
    serializer_class = StudentFeeInvoiceSerializer
    permission_classes = FEES_PERMS

    def get_queryset(self):
        user = self.request.user
        qs = StudentFeeInvoice.objects.select_related("student", "fee_structure").prefetch_related("items__category").order_by("-created_at")
        
        # If student, restrict to own invoices
        if user.groups.filter(name="student").exists():
            return qs.filter(student=user)
        
        # Admin filters
        student_id = self.request.query_params.get("student_id")
        status_filter = self.request.query_params.get("status")
        if student_id:
            qs = qs.filter(student_id=student_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
            
        return qs

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsAuthenticated(), IsSaaSOrCollegeAdmin(), RequiresModule("fees")()]
        return super().get_permissions()


class BulkGenerateInvoicesView(APIView):
    """
    POST: Generate invoices for multiple students based on filters.
    Payload: {
        "fee_structure_id": 1,
        "due_date": "YYYY-MM-DD",
        "department_id": 2, (optional)

        # Structured targeting (preferred going forward):
        "program_id": 5, "batch_id": 9, "semester_number": 3, "section_id": 12, (all optional)

        # Legacy free-text targeting (still fully supported, unchanged):
        "batch_academic_year": "2025-2026", "program_enrolled_in": "B.Tech CS",
        "current_semester_year": "Semester 1", (all optional)

        "force": true  # only needed if a structured filter above is given AND
                        # some matched students have not been individually
                        # backfilled onto that Program/Batch/Semester yet —
                        # see the 409 response below.
    }

    Roster resolution goes through resolve_student_roster (see
    services/academic_roster.py), which matches a student if EITHER their
    structured FK or their legacy string agrees with the criteria — nobody who
    would have matched under the old exact-string filtering is ever excluded by
    switching to structured criteria.

    Whenever a structured filter (program_id/batch_id/semester_number) is
    given, its equivalent legacy string is derived automatically unless the
    caller also supplied one explicitly. Without that, a student who plainly
    belongs to the selected Program/Batch/Semester but has not been
    individually backfilled onto it yet — their program/batch/current_semester_number
    are still null — would be silently skipped, reintroducing exactly the
    partial-match under-billing this change exists to prevent.
    """
    permission_classes = FEES_ADMIN_PERMS

    @transaction.atomic
    def post(self, request):
        structure_id = request.data.get("fee_structure_id")
        due_date = request.data.get("due_date")

        if not structure_id or not due_date:
            return Response(
                {"error": "fee_structure_id and due_date are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            structure = FeeStructure.objects.prefetch_related("items").get(id=structure_id)
        except FeeStructure.DoesNotExist:
            return Response({"error": "Fee structure not found."}, status=status.HTTP_404_NOT_FOUND)

        dept_id = request.data.get("department_id")
        program_id = request.data.get("program_id")
        batch_id = request.data.get("batch_id")
        semester_number = request.data.get("semester_number")
        section_id = request.data.get("section_id")
        legacy_program = request.data.get("program_enrolled_in")
        legacy_batch = request.data.get("batch_academic_year")
        legacy_semester = request.data.get("current_semester_year")

        any_fk_filter_given = bool(program_id or batch_id or semester_number or section_id)

        if program_id and not legacy_program:
            program_obj = Program.objects.filter(pk=program_id).first()
            if program_obj:
                legacy_program = program_obj.short_name or program_obj.code
        if batch_id and not legacy_batch:
            batch_obj = Batch.objects.filter(pk=batch_id).first()
            if batch_obj:
                legacy_batch = batch_obj.name
        if semester_number and not legacy_semester:
            legacy_semester = f"Semester {semester_number}"

        roster_qs, diagnostics = resolve_student_roster(
            department_id=dept_id,
            program_id=program_id, legacy_program=legacy_program,
            batch_id=batch_id, legacy_batch=legacy_batch,
            semester_number=semester_number, legacy_semester=legacy_semester,
            section_id=section_id,
        )

        if diagnostics["matched"] == 0:
            return Response(
                {"message": "No students found matching the specified criteria."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # This gate only ever applies when a structured filter was actually
        # given — a request using only the legacy fields (today's existing
        # behaviour) always has every matched student "unresolved by fk" by
        # definition, since there is no FK criterion to test against, and
        # blocking that would break the golden path for zero safety benefit:
        # resolve_student_roster already includes those students correctly.
        if any_fk_filter_given and diagnostics["unresolved_by_fk"] > 0 and not request.data.get("force"):
            return Response(
                {
                    "error": (
                        f"{diagnostics['unresolved_by_fk']} of {diagnostics['matched']} matched "
                        "students have not been individually backfilled onto the selected "
                        "Program/Batch/Semester yet — they still only match via their legacy "
                        "academic fields. Resend with force=true to generate for all matched "
                        "students anyway; nobody is excluded either way, this only confirms you "
                        "are aware some of them still need backfilling."
                    ),
                    "matched": diagnostics["matched"],
                    "unresolved_students_in_scope": diagnostics["unresolved_by_fk"],
                },
                status=status.HTTP_409_CONFLICT,
            )

        generated = 0
        skipped = 0

        for profile in roster_qs.select_related("user"):
            # StudentFeeInvoice.student+fee_structure is a DB-level unique
            # constraint (see models/fees.py); the .exists() check below is
            # just a fast, friendly pre-check — the except IntegrityError is
            # the actual guard under concurrent requests, where two requests
            # could both pass this check for the same student before either
            # commits.
            if StudentFeeInvoice.objects.filter(student=profile.user, fee_structure=structure).exists():
                skipped += 1
                continue

            total_amount = sum(item.amount for item in structure.items.all())

            try:
                with transaction.atomic():
                    invoice = StudentFeeInvoice.objects.create(
                        student=profile.user,
                        fee_structure=structure,
                        due_date=due_date,
                        total_amount=total_amount,
                        discount_amount=0,
                        paid_amount=0,
                        status=StudentFeeInvoice.STATUS_UNPAID
                    )
            except IntegrityError:
                skipped += 1
                continue

            for item in structure.items.all():
                StudentFeeInvoiceItem.objects.create(
                    invoice=invoice,
                    category=item.category,
                    amount=item.amount
                )
            generated += 1

        return Response({
            "message": f"Invoice generation completed. Generated: {generated}, Skipped: {skipped}.",
            "generated": generated,
            "skipped": skipped
        }, status=status.HTTP_201_CREATED)


class RecordFeePaymentView(APIView):
    """
    POST: Record a payment receipt against an invoice.
    Payload: {
        "amount_paid": 5000,
        "payment_method": "upi",
        "transaction_reference": "TXN123456", (optional)
        "remarks": "paid online" (optional)
    }
    """
    permission_classes = FEES_ADMIN_PERMS

    @transaction.atomic
    def post(self, request, invoice_id):
        try:
            invoice = StudentFeeInvoice.objects.get(id=invoice_id)
        except StudentFeeInvoice.DoesNotExist:
            return Response({"error": "Invoice not found."}, status=status.HTTP_404_NOT_FOUND)

        amount_paid = Decimal(str(request.data.get("amount_paid", 0)))
        method = request.data.get("payment_method")

        if amount_paid <= 0:
            return Response({"error": "amount_paid must be greater than zero."}, status=status.HTTP_400_BAD_REQUEST)

        from campusflow_app.models.finance import get_locked_financial_year_for_date
        locked_fy = get_locked_financial_year_for_date(timezone.now().date())
        if locked_fy:
            return Response(
                {"error": f"Financial year {locked_fy.label} is locked. New fee payments cannot be recorded against a closed year."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        valid_methods = [c[0] for c in FeePayment.METHOD_CHOICES]
        if method not in valid_methods:
            return Response({"error": f"Invalid payment method. Must be one of: {', '.join(valid_methods)}"}, status=status.HTTP_400_BAD_REQUEST)

        remaining = invoice.remaining_balance
        if amount_paid > remaining:
            return Response(
                {"error": f"Payment amount (₹{amount_paid}) exceeds the remaining due balance of ₹{remaining}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        payment = FeePayment.objects.create(
            invoice=invoice,
            amount_paid=amount_paid,
            payment_method=method,
            transaction_reference=request.data.get("transaction_reference", ""),
            remarks=request.data.get("remarks", ""),
            collected_by=request.user
        )

        return Response({
            "message": "Payment recorded successfully.",
            "receipt_number": payment.receipt_number,
            "paid_amount": str(invoice.paid_amount),
            "status": invoice.status,
            "remaining_balance": str(invoice.remaining_balance)
        }, status=status.HTTP_201_CREATED)


class FeePaymentListView(generics.ListAPIView):
    """
    GET /api/fees/payments/
    Admins can view all collections/receipts.
    Students can only view their own receipts.
    """
    serializer_class = FeePaymentSerializer
    permission_classes = FEES_PERMS

    def get_queryset(self):
        user = self.request.user
        qs = FeePayment.objects.select_related("invoice__student", "invoice__fee_structure").order_by("-payment_date")

        # If student, restrict
        if user.groups.filter(name="student").exists():
            return qs.filter(invoice__student=user)

        # Admin filters
        invoice_id = self.request.query_params.get("invoice_id")
        if invoice_id:
            qs = qs.filter(invoice_id=invoice_id)
        return qs


class FeeDashboardView(APIView):
    """
    GET /api/fees/dashboard/
    Get financial overview metrics: Collected, Outstanding Dues, Expected.
    """
    permission_classes = [IsAuthenticated, IsNotStudent, RequiresModule("fees")]

    def get(self, request):
        invoices = StudentFeeInvoice.objects.all()

        total_billed = invoices.aggregate(total=Sum('total_amount'))['total'] or Decimal(0)
        total_discount = invoices.aggregate(total=Sum('discount_amount'))['total'] or Decimal(0)
        total_collected = invoices.aggregate(total=Sum('paid_amount'))['total'] or Decimal(0)

        total_expected = total_billed - total_discount
        total_due = max(Decimal(0), total_expected - total_collected)

        # Category breakdown
        category_expected = StudentFeeInvoiceItem.objects.values('category__name').annotate(
            expected=Sum('amount')
        ).order_by('-expected')

        # Format stats
        stats = {
            "total_expected": str(total_expected),
            "total_collected": str(total_collected),
            "total_due": str(total_due),
            "total_discount": str(total_discount),
            "category_breakdown": [
                {
                    "category": item['category__name'],
                    "expected": str(item['expected'])
                } for item in category_expected
            ]
        }

        return Response(stats, status=status.HTTP_200_OK)
