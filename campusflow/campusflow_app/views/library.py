from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from ..models.library import Book, BookCopy, BookIssue
from ..serializers import BookSerializer, BookCopySerializer, BookIssueSerializer


class BookViewSet(viewsets.ModelViewSet):
    queryset = Book.objects.all().order_by('title')
    serializer_class = BookSerializer
    permission_classes = [IsAuthenticated]


class BookCopyViewSet(viewsets.ModelViewSet):
    queryset = BookCopy.objects.all().order_by('barcode')
    serializer_class = BookCopySerializer
    permission_classes = [IsAuthenticated]


class BookIssueViewSet(viewsets.ModelViewSet):
    queryset = BookIssue.objects.all().order_by('-issued_date')
    serializer_class = BookIssueSerializer
    permission_classes = [IsAuthenticated]
