from django.contrib import admin
from .models.department import Department
from .models.profile import StudentProfile, TeachingStaffProfile, NonTeachingStaffProfile
from .models.course import Course
from .models.schedule import Schedule
from .models.classroom import Classroom
from .models.lecture import Lecture
from .models.attendance_session import AttendanceSession
from .models.attendance import Attendance
from .models.face_embedding import FaceEmbedding
from .models.attendance_log import FaceAttendanceLog
from .models.fraud_alert import FraudAlert
from .models.device_reset import DeviceResetRequest


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
admin.site.register(FaceAttendanceLog)
admin.site.register(FraudAlert)
admin.site.register(DeviceResetRequest)

