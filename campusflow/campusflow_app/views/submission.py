from decimal import Decimal, InvalidOperation

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from ..models.assignment import Assignment
from ..models.submission import AssignmentSubmission
from ..permissions import RequiresModule, IsFacultyOrAbove, get_user_group, is_college_admin
from ..utils.file_validation import validate_attachment

class SubmissionListCreateView(APIView):
    """
    GET: List submissions for an assignment. Faculty/Admins see all; students see their own.
    POST: Submit assignment answers (students only, supports multipart attachments).
    """
    permission_classes = [IsAuthenticated, RequiresModule("assignments")]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, assignment_id):
        user = request.user
        user_group = get_user_group(user)

        try:
            assignment = Assignment.objects.get(id=assignment_id)
        except Assignment.DoesNotExist:
            return Response({"error": "Assignment not found."}, status=status.HTTP_404_NOT_FOUND)

        if user_group == 'student':
            # Students can only retrieve their own submission
            submissions = AssignmentSubmission.objects.filter(assignment=assignment, student=user)
        else:
            # Faculty/HOD/Admin can view all submissions
            submissions = AssignmentSubmission.objects.filter(assignment=assignment).select_related('student')

        data = []
        for s in submissions:
            data.append({
                "id": s.id,
                "assignment_id": s.assignment_id,
                "student_id": s.student.id,
                "student_username": s.student.username,
                "student_name": s.student.get_full_name() or s.student.username,
                "submitted_at": s.submitted_at.isoformat(),
                "attachment": s.attachment.url if s.attachment else None,
                "text_submission": s.text_submission,
                "grade": s.grade,
                "marks_obtained": str(s.marks_obtained) if s.marks_obtained is not None else None,
                "feedback": s.feedback,
                "status": s.status
            })
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request, assignment_id):
        user = request.user
        user_group = get_user_group(user)

        if user_group != 'student':
            return Response({"error": "Only students can submit assignments."}, status=status.HTTP_403_FORBIDDEN)

        try:
            assignment = Assignment.objects.get(id=assignment_id)
        except Assignment.DoesNotExist:
            return Response({"error": "Assignment not found."}, status=status.HTTP_404_NOT_FOUND)

        # Check if already submitted
        if AssignmentSubmission.objects.filter(assignment=assignment, student=user).exists():
            return Response({"error": "You have already submitted this assignment."}, status=status.HTTP_400_BAD_REQUEST)

        attachment = request.FILES.get('attachment')
        text_submission = request.data.get('text_submission', '').strip()

        if not attachment and not text_submission:
            return Response({"error": "Either file attachment or text response is required."}, status=status.HTTP_400_BAD_REQUEST)

        attachment_error = validate_attachment(attachment)
        if attachment_error:
            return Response({"error": attachment_error}, status=status.HTTP_400_BAD_REQUEST)

        submission = AssignmentSubmission.objects.create(
            assignment=assignment,
            student=user,
            attachment=attachment,
            text_submission=text_submission,
            status='submitted'
        )

        return Response({
            "message": "Assignment submitted successfully.",
            "id": submission.id
        }, status=status.HTTP_201_CREATED)


class SubmissionGradeView(APIView):
    """
    POST/PUT: Grade a student submission (Faculty/HOD/Admin only).
    """
    permission_classes = [IsAuthenticated, RequiresModule("assignments")]

    def post(self, request, pk):
        if not IsFacultyOrAbove().has_permission(request, self):
            return Response({"error": "Only Faculty and Admins can grade submissions."}, status=status.HTTP_403_FORBIDDEN)

        try:
            submission = AssignmentSubmission.objects.select_related('assignment').get(id=pk)
        except AssignmentSubmission.DoesNotExist:
            return Response({"error": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)

        grade = str(request.data.get('grade') or '').strip()
        feedback = str(request.data.get('feedback') or '').strip()
        raw_marks = request.data.get('marks_obtained')

        marks_obtained = None
        if raw_marks not in (None, ''):
            try:
                marks_obtained = Decimal(str(raw_marks))
            except InvalidOperation:
                return Response({"error": "marks_obtained must be a number."}, status=status.HTTP_400_BAD_REQUEST)
            max_marks = submission.assignment.max_marks
            if marks_obtained < 0 or (max_marks is not None and marks_obtained > max_marks):
                return Response(
                    {"error": f"marks_obtained must be between 0 and {max_marks if max_marks is not None else 'the maximum'}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not grade:
                grade = f"{marks_obtained}/{max_marks}" if max_marks is not None else str(marks_obtained)

        if not grade:
            return Response({"error": "Grade/marks is required."}, status=status.HTTP_400_BAD_REQUEST)

        if marks_obtained is not None:
            submission.marks_obtained = marks_obtained
        submission.grade = grade
        submission.feedback = feedback
        submission.status = 'graded'
        submission.save()

        return Response({
            "message": "Submission graded successfully.",
            "status": submission.status,
            "grade": submission.grade,
            "marks_obtained": str(submission.marks_obtained) if submission.marks_obtained is not None else None,
        }, status=status.HTTP_200_OK)
