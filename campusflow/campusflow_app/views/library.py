from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from ..models.library import Book, BookCopy, BookIssue
from ..serializers import BookSerializer, BookCopySerializer, BookIssueSerializer
from ..permissions import RequiresModule

LIBRARY_PERMS = [IsAuthenticated, RequiresModule("library")]


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

