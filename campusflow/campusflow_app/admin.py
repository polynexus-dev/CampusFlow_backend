from django.contrib import admin
from .models.department import Department
from .models.profile import StudentProfile, TeachingStaffProfile, NonTeachingStaffProfile
from .models.course import Course
from .models.schedule import Schedule
from .models.location import Location
from .models.attendance import Attendance


# Register your models here.
admin.site.register(Department)
admin.site.register(StudentProfile)
admin.site.register(TeachingStaffProfile)
admin.site.register(NonTeachingStaffProfile)
admin.site.register(Course)
admin.site.register(Schedule)
admin.site.register(Location)
admin.site.register(Attendance)
