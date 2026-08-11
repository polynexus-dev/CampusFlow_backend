from django.contrib import admin
from .models.department import Department
from .models.profile import StudentProfile, TeachingStaffProfile, NonTeachingStaffProfile
from .models.course import Course
from .models.schedule import Schedule
from .models.classroom import Classroom
from .models.lecture import Lecture
from .models.attendance_session import AttendanceSession
from .models.attendance import Attendance
from .models.face_embedding import FaceEmbedding, FaceEmbeddingSample
from .models.attendance_log import FaceAttendanceLog
from .models.fraud_alert import FraudAlert
from .models.device_reset import DeviceResetRequest
from .models.ai_grading import AIGradingSuggestion
from .models.risk_score import StudentRiskScore
from .models.accreditation_narrative import AccreditationNarrativeDraft
from .models.admissions import Lead, LeadActivity
from .models.timetable_generation import TimetableGenerationRun


# Register your models here.
admin.site.register(Department)
admin.site.register(StudentProfile)
admin.site.register(TeachingStaffProfile)
admin.site.register(NonTeachingStaffProfile)
admin.site.register(Course)
admin.site.register(Schedule)
admin.site.register(Classroom)
admin.site.register(Lecture)
admin.site.register(AttendanceSession)
admin.site.register(Attendance)
admin.site.register(FaceEmbedding)
admin.site.register(FaceEmbeddingSample)
admin.site.register(FaceAttendanceLog)
admin.site.register(FraudAlert)
admin.site.register(DeviceResetRequest)
admin.site.register(AIGradingSuggestion)
admin.site.register(StudentRiskScore)
admin.site.register(AccreditationNarrativeDraft)
admin.site.register(Lead)
admin.site.register(LeadActivity)
admin.site.register(TimetableGenerationRun)

