from django import forms
from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from import_export import resources, fields
from import_export.widgets import Widget, ForeignKeyWidget
from .models import Student, Subject, Marks, SubjectAttendance, UserProfile, Achievement, AllowedTeacher


# =========================================================
# CUSTOM IMPORT-EXPORT WIDGET
# =========================================================
class CleanFloatWidget(Widget):
    """Safely converts empty strings, invalid inputs, or missing Excel cells to None or float."""
    def clean(self, value, row=None, *args, **kwargs):
        if value is None:
            return None
        val_str = str(value).strip()
        if val_str == '' or val_str.lower() in ['none', 'nan', 'null', 'n/a', '-', 'null']:
            return None
        try:
            return float(val_str)
        except (ValueError, TypeError):
            return None


# =========================================================
# IMPORT-EXPORT RESOURCES
# =========================================================

# Sheet 1 Resource: Subject Assessment Structure Setup
class SubjectResource(resources.ModelResource):
    name = fields.Field(column_name='Subject Name', attribute='name')
    subject_type = fields.Field(column_name='Subject Type', attribute='subject_type')

    total_max_marks = fields.Field(column_name='Total Marks', attribute='total_max_marks', widget=CleanFloatWidget())
    max_theory_marks = fields.Field(column_name='Theory Max', attribute='max_theory_marks', widget=CleanFloatWidget())
    max_practical_marks = fields.Field(column_name='Practical Max', attribute='max_practical_marks', widget=CleanFloatWidget())
    max_internal_marks = fields.Field(column_name='Internal Max', attribute='max_internal_marks', widget=CleanFloatWidget())
    max_assignment_marks = fields.Field(column_name='Assignment Max', attribute='max_assignment_marks', widget=CleanFloatWidget())
    max_presentation_marks = fields.Field(column_name='Presentation Max', attribute='max_presentation_marks', widget=CleanFloatWidget())

    unit_1_max = fields.Field(column_name='Unit 1 Max', attribute='unit_1_max', widget=CleanFloatWidget())
    unit_2_max = fields.Field(column_name='Unit 2 Max', attribute='unit_2_max', widget=CleanFloatWidget())
    unit_3_max = fields.Field(column_name='Unit 3 Max', attribute='unit_3_max', widget=CleanFloatWidget())
    unit_4_max = fields.Field(column_name='Unit 4 Max', attribute='unit_4_max', widget=CleanFloatWidget())

    class Meta:
        model = Subject
        import_id_fields = ('name',)
        fields = (
            'name', 'subject_type', 'total_max_marks',
            'max_theory_marks', 'max_practical_marks', 'max_internal_marks',
            'max_assignment_marks', 'max_presentation_marks',
            'unit_1_max', 'unit_2_max', 'unit_3_max', 'unit_4_max'
        )


# Sheet 2 Resource: Student Obtained Marks
class MarksResource(resources.ModelResource):
    roll_number = fields.Field(
        column_name='Roll Number',
        attribute='student',
        widget=ForeignKeyWidget(Student, field='roll_number')
    )
    subject_name = fields.Field(
        column_name='Subject Name',
        attribute='subject',
        widget=ForeignKeyWidget(Subject, field='name')
    )

    semester = fields.Field(column_name='Semester', attribute='semester', widget=CleanFloatWidget())
    unit_1_marks = fields.Field(column_name='Unit 1', attribute='unit_1_marks', widget=CleanFloatWidget())
    unit_2_marks = fields.Field(column_name='Unit 2', attribute='unit_2_marks', widget=CleanFloatWidget())
    unit_3_marks = fields.Field(column_name='Unit 3', attribute='unit_3_marks', widget=CleanFloatWidget())
    unit_4_marks = fields.Field(column_name='Unit 4', attribute='unit_4_marks', widget=CleanFloatWidget())

    practical_marks = fields.Field(column_name='Practical', attribute='practical_marks', widget=CleanFloatWidget())
    internal_marks = fields.Field(column_name='Internal', attribute='internal_marks', widget=CleanFloatWidget())
    assignment_marks = fields.Field(column_name='Assignment', attribute='assignment_marks', widget=CleanFloatWidget())
    presentation_marks = fields.Field(column_name='Presentation', attribute='presentation_marks', widget=CleanFloatWidget())

    class Meta:
        model = Marks
        import_id_fields = ('roll_number', 'subject_name', 'semester')
        fields = (
            'roll_number', 'subject_name', 'semester',
            'unit_1_marks', 'unit_2_marks', 'unit_3_marks', 'unit_4_marks',
            'practical_marks', 'internal_marks', 'assignment_marks', 'presentation_marks'
        )
        skip_unchanged = False
        report_skipped = False

    def before_import_row(self, row, **kwargs):
        """Ensures Student and Subject exist prior to mapping marks."""
        roll = str(row.get('Roll Number', '')).strip()
        student_name = str(row.get('Student Name', '')).strip()
        subj_name = str(row.get('Subject Name', '')).strip()

        if roll:
            Student.objects.get_or_create(
                roll_number=roll,
                defaults={'name': student_name or roll}
            )
        if subj_name:
            Subject.objects.get_or_create(name=subj_name)


# Sheet 3 Resource: Subject Attendance Records (Theory & Practical)
class SubjectAttendanceResource(resources.ModelResource):
    roll_number = fields.Field(
        column_name='Roll Number',
        attribute='student',
        widget=ForeignKeyWidget(Student, field='roll_number')
    )
    subject_name = fields.Field(
        column_name='Subject Name',
        attribute='subject',
        widget=ForeignKeyWidget(Subject, field='name')
    )
    semester = fields.Field(column_name='Semester', attribute='semester', widget=CleanFloatWidget())

    theory_attended = fields.Field(column_name='Theory Attended', attribute='theory_attended', widget=CleanFloatWidget())
    theory_total = fields.Field(column_name='Theory Total', attribute='theory_total', widget=CleanFloatWidget())
    practical_attended = fields.Field(column_name='Practical Attended', attribute='practical_attended', widget=CleanFloatWidget())
    practical_total = fields.Field(column_name='Practical Total', attribute='practical_total', widget=CleanFloatWidget())

    class Meta:
        model = SubjectAttendance
        import_id_fields = ('roll_number', 'subject_name', 'semester')
        fields = (
            'roll_number', 'subject_name', 'semester',
            'theory_attended', 'theory_total',
            'practical_attended', 'practical_total'
        )

    def before_import_row(self, row, **kwargs):
        """Ensures Student and Subject exist prior to mapping attendance."""
        roll = str(row.get('Roll Number', '')).strip()
        student_name = str(row.get('Student Name', '')).strip()
        subj_name = str(row.get('Subject Name', '')).strip()

        if roll:
            Student.objects.get_or_create(
                roll_number=roll,
                defaults={'name': student_name or roll}
            )
        if subj_name:
            Subject.objects.get_or_create(name=subj_name)


class StudentResource(resources.ModelResource):
    class Meta:
        model = Student
        import_id_fields = ('roll_number',)
        fields = ('name', 'roll_number', 'year', 'programme', 'part')


# =========================================================
# 1. INLINE CONFIGURATIONS
# =========================================================
class MarksInline(admin.StackedInline):
    model = Marks
    extra = 0
    classes = ['collapse']
    readonly_fields = (
        'get_sem_exam_display', 'total_internal_marks', 'total_marks',
        'percentage', 'grade', 'result_status', 'weakest_unit', 'strongest_unit'
    )

    fieldsets = (
        ('Subject & Semester', {
            'fields': (('subject', 'semester'),)
        }),
        ('Semester End Examination (Units 1-4)', {
            'fields': (
                ('unit_1_marks', 'unit_2_marks', 'unit_3_marks', 'unit_4_marks'),
                'get_sem_exam_display'
            )
        }),
        ('Internal & Assessment Components', {
            'fields': (
                ('internal_marks', 'assignment_marks', 'presentation_marks', 'practical_marks'),
                'total_internal_marks'
            )
        }),
        ('Overall Performance Summary', {
            'fields': (
                ('total_marks', 'percentage', 'grade', 'result_status'),
                ('weakest_unit', 'strongest_unit')
            )
        }),
    )

    # FIX (requirement #6): was showing the raw `semester_exam_marks` field
    # directly, which renders as 0 or 0.0 for a practical-only subject.
    # This uses Marks.semester_exam_display (added in models.py) so the
    # admin panel shows the same "N/A" the dashboards do, instead of a
    # misleading numeric zero.
    @admin.display(description='Semester Exam Marks')
    def get_sem_exam_display(self, obj):
        return obj.semester_exam_display


class SubjectAttendanceInline(admin.TabularInline):
    model = SubjectAttendance
    extra = 0
    readonly_fields = ('get_theory_percentage', 'get_practical_percentage', 'get_overall_percentage')

    @admin.display(description='Theory %')
    def get_theory_percentage(self, obj):
        val = obj.theory_percentage
        return f"{val}%" if val is not None else "N/A"

    @admin.display(description='Practical %')
    def get_practical_percentage(self, obj):
        val = obj.practical_percentage
        return f"{val}%" if val is not None else "N/A"

    @admin.display(description='Overall Subject %')
    def get_overall_percentage(self, obj):
        return f"{obj.overall_subject_percentage}%"


class AchievementInline(admin.TabularInline):
    model = Achievement
    extra = 0


# =========================================================
# 2. MODEL ADMIN REGISTRATIONS
# =========================================================
@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('name', 'roll_number', 'programme', 'part', 'year')
    search_fields = ('name', 'roll_number')
    list_filter = ('programme', 'part', 'year')
    inlines = [MarksInline, SubjectAttendanceInline, AchievementInline]


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'subject_type', 'total_max_marks',
        'max_theory_marks', 'max_practical_marks', 'max_internal_marks'
    )
    list_filter = ('subject_type',)
    search_fields = ('name',)


@admin.register(SubjectAttendance)
class SubjectAttendanceAdmin(admin.ModelAdmin):
    list_display = (
        'student', 'subject', 'semester',
        'get_theory_percentage', 'get_practical_percentage', 'get_overall_percentage'
    )
    list_filter = ('semester', 'subject')
    search_fields = ('student__name', 'student__roll_number', 'subject__name')
    autocomplete_fields = ['student', 'subject']
    readonly_fields = (
        'get_theory_percentage',
        'get_practical_percentage',
        'get_overall_percentage',
        'total_classes_conducted',
        'total_attended'
    )

    @admin.display(description='Theory %')
    def get_theory_percentage(self, obj):
        val = obj.theory_percentage
        return f"{val}%" if val is not None else "N/A"

    @admin.display(description='Practical %')
    def get_practical_percentage(self, obj):
        val = obj.practical_percentage
        return f"{val}%" if val is not None else "N/A"

    @admin.display(description='Overall %')
    def get_overall_percentage(self, obj):
        return f"{obj.overall_subject_percentage}%"


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ('student', 'title', 'category', 'date_achieved')
    search_fields = ('student__name', 'title')
    list_filter = ('category',)
    autocomplete_fields = ['student']


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'college_email', 'roll_number')
    list_filter = ('role',)
    search_fields = ('user__username', 'college_email', 'roll_number')


@admin.register(AllowedTeacher)
class AllowedTeacherAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'is_registered')
    search_fields = ('name', 'email')

    def is_primary_admin(self, request):
        """
        Returns True ONLY for superusers.

        FIX: the previous version did:
            if hasattr(request.user, 'profile'):
                return request.user.profile.role != UserProfile.Role.TEACHER
            return not request.user.email.endswith('@college.edu')

        That was broken two ways:
        1. `hasattr(request.user, 'profile')` is silently False whenever the
           actual related_name on UserProfile's OneToOneField is
           'userprofile' (which is what the rest of the app assumes) — so it
           always fell through to the second line.
        2. The fallback called `request.user.email` with no
           `is_authenticated` check at all. On `/admin/login/` and right
           after `/admin/logout/`, request.user is AnonymousUser, which has
           no `.email` attribute — this was your
           "AttributeError: 'AnonymousUser' object has no attribute 'email'"
           crash. It was also inverted logic: it granted "primary admin"
           (full AllowedTeacher access) to any non-@college.edu account,
           rather than restricting to superusers as required.

        The fix below is a single, safe check: `is_superuser` is always a
        real (False) attribute on AnonymousUser too, so this never raises
        and always enforces "superusers only".
        """
        return bool(getattr(request.user, 'is_superuser', False))

    def has_module_permission(self, request):
        # Hides the "Allowed Teachers" section from the admin index entirely
        # for non-superusers.
        return self.is_primary_admin(request)

    def has_view_permission(self, request, obj=None):
        return self.is_primary_admin(request)

    def has_add_permission(self, request):
        return self.is_primary_admin(request)

    def has_change_permission(self, request, obj=None):
        return self.is_primary_admin(request)

    def has_delete_permission(self, request, obj=None):
        return self.is_primary_admin(request)


# =========================================================
# 3. ADMIN BRANDING TITLE (top-left "site name")
# =========================================================
# CORRECTION from the previous version of this file: Django's admin does
# NOT use `site_header` for the "Welcome, X" greeting in the top-right of
# the page — that greeting is a separate, hardcoded template block
# (`welcome-msg`) that renders `user.get_short_name` (falling back to
# `get_username`). `site_header` only controls the top-LEFT brand title
# (`<h1 id="site-name">`). Setting site_header to "Welcome, ..." here was
# putting the wrong text in the wrong place and didn't touch the actual
# greeting at all.
#
# ROOT CAUSE OF "Welcome, Prof. " (empty name), requirement #4: User.
# get_short_name() returns ONLY `first_name`. In first_time_setup(), a
# teacher's AllowedTeacher.name like "Prof. Alex Paul" gets split as:
#   first_name = "Prof."      (parts[0])
#   last_name  = "Alex Paul"  (parts[1])
# so get_short_name() returns just "Prof." — exactly matching the bug.
# get_full_name() (first_name + " " + last_name) correctly returns
# "Prof. Alex Paul", so the real fix is to make the admin welcome-msg
# template block use get_full_name instead of the default get_short_name.
# That override lives in templates/admin/base_site.html (see below /
# separate file) since it's template markup, not Python.
#
# This patch is now scoped to ONLY the top-left branding title, which is a
# legitimate, harmless customization (shows the school/portal name there
# instead of "Django administration") — it no longer touches the greeting.
_original_each_context = AdminSite.each_context


def _each_context_with_branding(self, request):
    context = _original_each_context(self, request)
    context.setdefault('site_header', 'College Analytics Admin')
    return context


AdminSite.each_context = _each_context_with_branding

# =========================================================
# 4. "VIEW SITE" LINK -> /dashboard/ (requirement #3)
# =========================================================
# Configures the built-in "View site" link in the admin usertools row to
# point at the dashboard instead of Django's default ("/"). This is a
# separate, smaller fix from the explicit "Dashboard" button added via
# templates/admin/base_site.html below — keeping both since the button is
# more visible and this keeps the existing default link consistent too.
admin.site.site_url = '/dashboard/'