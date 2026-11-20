import datetime

from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from ..models.library import Book, BookCopy, BookIssue
from ..models.profile import StudentProfile
from ..serializers import BookSerializer, BookCopySerializer, BookIssueSerializer
from ..permissions import RequiresModule, get_user_group, is_college_admin, is_saas_admin


def is_library_manager(user):
    """Who may change library records: the Librarian role and College Admins."""
    return is_saas_admin(user) or is_college_admin(user) or get_user_group(user) == 'Librarian'


class IsLibraryManagerOrReadOnly(BasePermission):
    """
    Several roles hold the 'library' module only to read it (students see their
    own issued books). Without this, any of them could create/edit/delete books,
    copies and issue records through the API.
    """
    message = "Only the Librarian or a College Admin can change library records."

    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or is_library_manager(request.user)


LIBRARY_PERMS = [IsAuthenticated, RequiresModule("library"), IsLibraryManagerOrReadOnly]

# Self-service renewal limits for students.
RENEWAL_DAYS = 14
MAX_RENEWALS = 2


class BookViewSet(viewsets.ModelViewSet):
    queryset = Book.objects.all().order_by('title')
    serializer_class = BookSerializer
    permission_classes = LIBRARY_PERMS


class BookCopyViewSet(viewsets.ModelViewSet):
    queryset = BookCopy.objects.select_related('book').all().order_by('barcode')
    serializer_class = BookCopySerializer
    permission_classes = LIBRARY_PERMS


class BookIssueViewSet(viewsets.ModelViewSet):
    serializer_class = BookIssueSerializer
    permission_classes = LIBRARY_PERMS

    def get_permissions(self):
        # Borrowers renew their own books, so `renew` skips the
        # librarian-only write check; the action itself checks ownership.
        if getattr(self, "action", None) == "renew":
            return [IsAuthenticated(), RequiresModule("library")()]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        queryset = BookIssue.objects.select_related('book_copy__book', 'student__user', 'staff_user').all().order_by('-issued_date')
        
        # If student logs in, filter results to their own profile
        if hasattr(user, 'student_profile'):
            return queryset.filter(student=user.student_profile)
            
        return queryset

    @action(detail=True, methods=["post"])
    def renew(self, request, pk=None):
        """
        POST /api/book-issues/<id>/renew/
        Extends the due date by RENEWAL_DAYS from the current due date. The
        borrowing student may renew their own book up to MAX_RENEWALS times
        while it is not yet overdue; an overdue book has to come back to the
        desk (fine first). The Librarian / College Admin can renew any loan.
        """
        manager = is_library_manager(request.user)
        with transaction.atomic():
            issue = BookIssue.objects.select_for_update(of=("self",)).select_related("book_copy__book", "student").filter(pk=pk).first()
            if issue is None:
                return Response({"error": "Loan not found."}, status=status.HTTP_404_NOT_FOUND)
            student = getattr(request.user, "student_profile", None)
            if not manager and (student is None or issue.student_id != student.id):
                return Response({"error": "You can only renew your own books."}, status=status.HTTP_403_FORBIDDEN)
            if issue.status == "Returned" or issue.returned_date:
                return Response({"error": "This book has already been returned."}, status=status.HTTP_400_BAD_REQUEST)
            today = timezone.localdate()
            if not manager and issue.due_date < today:
                return Response(
                    {"error": "This book is overdue. Please return it at the library desk."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not manager and issue.renewal_count >= MAX_RENEWALS:
                return Response(
                    {"error": f"This book has already been renewed {MAX_RENEWALS} times. Please return it at the library desk."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            issue.due_date = max(issue.due_date, today) + datetime.timedelta(days=RENEWAL_DAYS)
            issue.renewal_count += 1
            if issue.status == "Overdue":
                issue.status = "Issued"
            issue.save(update_fields=["due_date", "renewal_count", "status", "updated_at"])
        return Response(BookIssueSerializer(issue).data)


class LibraryBorrowerListView(APIView):
    """
    GET /api/library/borrowers/ — the student picker for issuing a book.
    Only what the picker needs (no contact/ID/address data), so the Librarian
    doesn't need the full student-profile API, which is Faculty-and-above.
    Same shape as /api/student/user/ rows so the frontend picker is unchanged.
    """
    permission_classes = [IsAuthenticated, RequiresModule("library")]

    def get(self, request):
        if not is_library_manager(request.user):
            return Response({"detail": IsLibraryManagerOrReadOnly.message}, status=403)
        students = StudentProfile.objects.select_related('user', 'department').order_by('student_id')
        return Response([
            {"id": sp.id, "student_id": sp.student_id,
             "user": {"first_name": sp.user.first_name, "last_name": sp.user.last_name},
             "department": sp.department.name if sp.department_id else None}
            for sp in students
        ])

