from rest_framework import viewsets
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

    def get_queryset(self):
        user = self.request.user
        queryset = BookIssue.objects.select_related('book_copy__book', 'student__user', 'staff_user').all().order_by('-issued_date')
        
        # If student logs in, filter results to their own profile
        if hasattr(user, 'student_profile'):
            return queryset.filter(student=user.student_profile)
            
        return queryset


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

