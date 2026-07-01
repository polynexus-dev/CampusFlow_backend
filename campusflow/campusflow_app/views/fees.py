from rest_framework import viewsets, status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework import serializers as drf_serializers
from django.db import transaction
from django.db.models import Sum, Q
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal

from campusflow_app.models import (
    FeeCategory, FeeStructure, FeeStructureItem,
    StudentFeeInvoice, StudentFeeInvoiceItem, FeePayment
)
from campusflow_app.models.profile import StudentProfile
from campusflow_app.permissions import IsSaaSOrCollegeAdmin, IsNotStudent

User = get_user_model()


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
    total_amount = drf_serializers.SerializerMethodField()

    class Meta:
        model = FeeStructure
        fields = [
            "id", "name", "department", "department_name",
            "batch_academic_year", "program_enrolled_in",
            "current_semester_year", "items", "total_amount",
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
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsAuthenticated(), IsSaaSOrCollegeAdmin()]
        return super().get_permissions()


class FeeStructureViewSet(viewsets.ModelViewSet):
    """
    CRUD fee structure templates. Only admins.
    """
    queryset = FeeStructure.objects.all().prefetch_related("items__category", "department").order_by("-created_at")
    serializer_class = FeeStructureSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]


class StudentFeeInvoiceViewSet(viewsets.ModelViewSet):
    """
    Manage student invoices.
    Admins can see all, students can only see their own.
    """
    serializer_class = StudentFeeInvoiceSerializer
    permission_classes = [IsAuthenticated]

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
            return [IsAuthenticated(), IsSaaSOrCollegeAdmin()]
        return super().get_permissions()


class BulkGenerateInvoicesView(APIView):
    """
    POST: Generate invoices for multiple students based on filters.
    Payload: {
        "fee_structure_id": 1,
        "due_date": "YYYY-MM-DD",
        "department_id": 2, (optional)
        "batch_academic_year": "2025-2026", (optional)
        "program_enrolled_in": "B.Tech CS", (optional)
        "current_semester_year": "Semester 1" (optional)
    }
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

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

        # Filters to find student profiles
        profiles_query = StudentProfile.objects.select_related("user")
        
        dept_id = request.data.get("department_id")
        batch = request.data.get("batch_academic_year")
        program = request.data.get("program_enrolled_in")
        semester = request.data.get("current_semester_year")

        if dept_id:
            profiles_query = profiles_query.filter(department_id=dept_id)
        if batch:
            profiles_query = profiles_query.filter(batch_academic_year=batch)
        if program:
            profiles_query = profiles_query.filter(program_enrolled_in=program)
        if semester:
            profiles_query = profiles_query.filter(current_semester_year=semester)

        if not profiles_query.exists():
            return Response(
                {"message": "No students found matching the specified criteria."},
                status=status.HTTP_400_BAD_REQUEST
            )

        generated = 0
        skipped = 0

        for profile in profiles_query:
            # Prevent double invoicing for same structure/student
            if StudentFeeInvoice.objects.filter(student=profile.user, fee_structure=structure).exists():
                skipped += 1
                continue

            total_amount = sum(item.amount for item in structure.items.all())
            
            invoice = StudentFeeInvoice.objects.create(
                student=profile.user,
                fee_structure=structure,
                due_date=due_date,
                total_amount=total_amount,
                discount_amount=0,
                paid_amount=0,
                status=StudentFeeInvoice.STATUS_UNPAID
            )

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
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

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
    permission_classes = [IsAuthenticated]

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
    permission_classes = [IsAuthenticated, IsNotStudent]

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
