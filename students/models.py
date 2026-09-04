# students/models.py
from django.db import models
from django.contrib.auth.models import User
import os
from django.db import transaction

# =========================================================
# CHOICES & CONSTANTS
# =========================================================
PROGRAMME_CHOICES = [
    ('FMCS', 'M.Sc. Computer Science (FMCS)'),
    ('SMCS', 'M.Sc. Computer Science (SMCS)'),
    ('BSC', 'B.Sc. Computer Science'),
]

PART_CHOICES = [
    ('PART1', 'Part I'),
    ('PART2', 'Part II'),
    ('FY', 'First Year'),
    ('SY', 'Second Year'),
    ('TY', 'Third Year'),
]

YEAR_CHOICES = [
    ('FY', 'B.Sc First Year'),
    ('SY', 'B.Sc Second Year'),
    ('TY', 'B.Sc Third Year'),
    ('MSC1', 'M.Sc Part 1'),
    ('MSC2', 'M.Sc Part 2'),
]

ROLE_CHOICES = [
    ('TEACHER', 'Teacher'),
    ('STUDENT', 'Student'),
]


# =========================================================
# CENTRALIZED GRADE CALCULATION (requirement #3)
# =========================================================
def calculate_grade(total_score):
    """
    Single source of truth for letter grades across the whole app.
    Every view, model, serializer, and template filter that needs a grade
    from a percentage/total-out-of-100 score MUST call this function instead
    of re-implementing the thresholds inline. Previously there were at least
    two different scales duplicated across the codebase (one in
    Marks.save(), a different one inline in analytics_dashboard() in
    views.py) — that's what this replaces.

    Scale (exact, as specified):
        90.00 - 100.00  -> 'O'
        80.00 - 89.99   -> 'A+'
        70.00 - 79.99   -> 'A'
        60.00 - 69.99   -> 'B+'
        55.00 - 59.99   -> 'B'
        50.00 - 54.99   -> 'C'
        40.00 - 49.99   -> 'D/P'
        below 40.00     -> 'F'

    Accepts None safely (returns 'F') so callers don't need to guard against
    missing scores themselves.
    """
    if total_score is None:
        return 'F'
    try:
        score = float(total_score)
    except (TypeError, ValueError):
        return 'F'

    if score >= 90:
        return 'O'
    elif score >= 80:
        return 'A+'
    elif score >= 70:
        return 'A'
    elif score >= 60:
        return 'B+'
    elif score >= 55:
        return 'B'
    elif score >= 50:
        return 'C'
    elif score >= 40:
        return 'D/P'
    else:
        return 'F'


def calculate_result_status(total_score):
    """
    Centralized PASS/FAIL rule (requirement #4): strictly on the total
    combined score out of 100. No separate per-component pass/fail.
    """
    if total_score is None:
        return 'FAIL'
    try:
        score = float(total_score)
    except (TypeError, ValueError):
        return 'FAIL'
    return 'PASS' if score >= 40 else 'FAIL'


# =========================================================
# 1. STUDENT MODEL
# =========================================================
class Student(models.Model):
    name = models.CharField(max_length=100, default='Student')
    roll_number = models.CharField(max_length=50, unique=True)

    # Independent Programme and Academic Part Tracking
    programme = models.CharField(max_length=20, choices=PROGRAMME_CHOICES, default='BSC')
    part = models.CharField(max_length=10, choices=PART_CHOICES, default='FY')
    year = models.CharField(max_length=10, choices=YEAR_CHOICES, default='FY')

    # Batch-tracking: which ExcelBatch created this student (nullable)
    created_in_batch = models.ForeignKey('ExcelBatch', null=True, blank=True, on_delete=models.SET_NULL, related_name='created_students')

    def auto_assign_year_from_roll(self):
        """
        Strict MSc/BSc Roll Number rules:
        - Starts with 'FMCS' -> MSc Part 1 / First Year
        - Starts with 'SMCS' -> MSc Part 2 / Second Year
        - Starts with 'FCS'/'FC'/'FYCS'/'F' -> BSc First Year
        - Starts with 'SCS'/'SC'/'SYCS'/'S' -> BSc Second Year
        - Starts with 'TCS'/'TC'/'TYCS'/'T' -> BSc Third Year
        """
        roll = str(self.roll_number).strip().upper()

        if roll.startswith('FMCS'):
            self.programme = 'FMCS'
            self.part = 'PART1'
            self.year = 'MSC1'
        elif roll.startswith('SMCS'):
            self.programme = 'SMCS'
            self.part = 'PART2'
            self.year = 'MSC2'
        elif roll.startswith(('FCS', 'FC', 'FYCS', 'F')):
            self.programme = 'BSC'
            self.part = 'FY'
            self.year = 'FY'
        elif roll.startswith(('SCS', 'SC', 'SYCS', 'S')):
            self.programme = 'BSC'
            self.part = 'SY'
            self.year = 'SY'
        elif roll.startswith(('TCS', 'TC', 'TYCS', 'T')):
            self.programme = 'BSC'
            self.part = 'TY'
            self.year = 'TY'
        else:
            # Fallback for unrecognized prefix
            self.programme = 'BSC'
            self.part = 'FY'
            self.year = 'FY'

    def save(self, *args, **kwargs):
        self.auto_assign_year_from_roll()

        # FIX (issue #2 — login/reset bug): normalize roll_number to a
        # single consistent case so it always matches the User.username the
        # post_save signal below generates (username = roll_number.lower()).
        # Previously roll_number was stored in WHATEVER case it was entered
        # (e.g. "FCS001" from an Excel upload), while the signal always
        # lowercased it for the username — so a student typing their roll
        # number in the case printed on their ID card could fail Django's
        # case-sensitive authenticate() even with the correct password,
        # and views.py's fallback logic then always reported "Wrong
        # password" regardless of whether it actually was.
        if self.roll_number:
            self.roll_number = str(self.roll_number).strip().upper()

        if not self.name or self.name.strip() == '':
            self.name = f"Student {self.roll_number}"
        super().save(*args, **kwargs)

    @classmethod
    def get_or_create_from_roll(cls, roll_number, name=None):
        """
        Helper method to look up student by roll number or auto-create if missing.
        """
        roll = str(roll_number).strip().upper()
        student = cls.objects.filter(roll_number=roll).first()
        if not student:
            display_name = name.strip() if name and str(name).strip() else f"Student {roll}"
            student = cls(roll_number=roll, name=display_name)
            student.save()
        elif name and student.name.startswith("Student "):
            student.name = name.strip()
            student.save()
        return student

    def calculate_overall_attendance(self):
        """
        Calculates aggregate overall attendance percentage across all subjects.
        """
        attendances = self.subject_attendances.all()
        total_conducted = sum(a.total_classes_conducted for a in attendances)
        total_attended = sum(a.total_attended for a in attendances)
        if total_conducted > 0:
            return round((total_attended / total_conducted) * 100, 1)
        return 0.0

    def calculate_academic_average(self):
        """
        Calculates average percentage score across all subjects.
        """
        marks_qs = self.marks.all()
        if marks_qs.exists():
            avg_pct = sum(m.percentage for m in marks_qs) / marks_qs.count()
            return round(avg_pct, 1)
        return 0.0

    def get_360_status(self):
        """
        Actionable 360° Risk Assessment combining Academics & Attendance.
        """
        att_pct = self.calculate_overall_attendance()
        acad_avg = self.calculate_academic_average()

        is_low_att = att_pct < 75.0 if self.subject_attendances.exists() else False
        is_low_acad = acad_avg < 40.0 if self.marks.exists() else False

        if is_low_att and is_low_acad:
            return {'label': 'Critical (Both)', 'color': 'danger', 'code': 'CRITICAL'}
        elif is_low_att:
            return {'label': 'Low Attendance', 'color': 'warning text-dark', 'code': 'ATT_RISK'}
        elif is_low_acad:
            return {'label': 'Academic Risk', 'color': 'warning text-dark', 'code': 'ACAD_RISK'}
        else:
            return {'label': 'Good', 'color': 'success', 'code': 'GOOD'}

    def __str__(self):
        return f"{self.name} ({self.roll_number})"


# =========================================================
# 2. SUBJECT MODEL
# =========================================================
class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)
    subject_type = models.CharField(max_length=50, default='THEORY')

    total_max_marks = models.FloatField(default=100.0)
    max_theory_marks = models.FloatField(default=0.0)
    max_practical_marks = models.FloatField(default=0.0)
    max_internal_marks = models.FloatField(default=0.0)
    max_assignment_marks = models.FloatField(default=0.0)
    max_presentation_marks = models.FloatField(default=0.0)

    unit_1_max = models.FloatField(default=0.0)
    unit_2_max = models.FloatField(default=0.0)
    unit_3_max = models.FloatField(default=0.0)
    unit_4_max = models.FloatField(default=0.0)

    @property
    def computed_total_max(self):
        sub_total = (
            (self.max_theory_marks or 0.0) +
            (self.max_practical_marks or 0.0) +
            (self.max_internal_marks or 0.0) +
            (self.max_assignment_marks or 0.0) +
            (self.max_presentation_marks or 0.0)
        )
        return sub_total if sub_total > 0 else (self.total_max_marks or 100.0)

    @property
    def is_practical_only(self):
        """
        Used for the Sem Exam 'N/A' display fix (requirement #5): a subject
        counts as practical-only when it's explicitly typed PRACTICAL, or
        when it simply has no theory component configured at all.
        """
        return (self.subject_type or '').strip().upper() == 'PRACTICAL' or not self.max_theory_marks

    def __str__(self):
        return f"{self.name} ({self.subject_type})"


# =========================================================
# 3. MARKS MODEL
# =========================================================
class Marks(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='marks')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    semester = models.IntegerField(default=1)

    unit_1_marks = models.FloatField(null=True, blank=True)
    unit_2_marks = models.FloatField(null=True, blank=True)
    unit_3_marks = models.FloatField(null=True, blank=True)
    unit_4_marks = models.FloatField(null=True, blank=True)

    practical_marks = models.FloatField(null=True, blank=True)
    internal_marks = models.FloatField(null=True, blank=True)
    assignment_marks = models.FloatField(null=True, blank=True)
    presentation_marks = models.FloatField(null=True, blank=True)

    # NOTE: stays a nullable FloatField — see semester_exam_display below for
    # why "N/A" is handled as a display property instead of stored here
    # (requirement #5). Storing the literal string "N/A" in a FloatField
    # isn't possible without a schema/migration change and would break every
    # place that sums this field numerically (calculated totals, dossier
    # aggregates, etc.) — the display property gives templates a clean,
    # float-formatting-safe value without touching the schema.
    semester_exam_marks = models.FloatField(null=True, blank=True)
    total_internal_marks = models.FloatField(null=True, blank=True)
    total_marks = models.FloatField(null=True, blank=True)
    percentage = models.FloatField(default=0.0)
    grade = models.CharField(max_length=5, blank=True)
    result_status = models.CharField(max_length=10, blank=True)

    weakest_unit = models.CharField(max_length=100, blank=True)
    strongest_unit = models.CharField(max_length=100, blank=True)

    # Track which Excel batch created/updated this marks row
    excel_batch = models.ForeignKey('ExcelBatch', null=True, blank=True, on_delete=models.SET_NULL, related_name='marks_batch')

    class Meta:
        unique_together = ('student', 'subject', 'semester')

    @property
    def calculated_total(self):
        """
        Requirement #4: sum whichever active components exist — internal,
        assignment, presentation, practical. No per-component pass/fail is
        computed anywhere; these are combined into one total only.
        """
        return (
            (self.internal_marks or 0.0) +
            (self.practical_marks or 0.0) +
            (self.assignment_marks or 0.0) +
            (self.presentation_marks or 0.0)
        )

    @property
    def semester_exam_display(self):
        """
        Requirement #5: for a practical-only subject (or one with no theory
        component configured), the Sem Exam column must show the literal
        string "N/A" — never 0, 0.0, None, or a dash. Templates should use
        this property instead of the raw semester_exam_marks field.
        """
        if self.subject and self.subject.is_practical_only:
            return "N/A"
        if self.semester_exam_marks is None:
            return "N/A"
        return self.semester_exam_marks

    def save(self, *args, **kwargs):
        def clean_val(val):
            if val is None or str(val).strip() == '':
                return None
            try:
                return float(val)
            except ValueError:
                return None

        u1 = clean_val(self.unit_1_marks)
        u2 = clean_val(self.unit_2_marks)
        u3 = clean_val(self.unit_3_marks)
        u4 = clean_val(self.unit_4_marks)

        p_marks = clean_val(self.practical_marks)
        i_marks = clean_val(self.internal_marks)
        a_marks = clean_val(self.assignment_marks)
        pr_marks = clean_val(self.presentation_marks)

        # Keep these normalized/consistent regardless of subject type —
        # used by calculated_total() above.
        self.practical_marks = p_marks
        self.internal_marks = i_marks
        self.assignment_marks = a_marks
        self.presentation_marks = pr_marks

        units = {'Unit 1': u1, 'Unit 2': u2, 'Unit 3': u3, 'Unit 4': u4}
        valid_units = {k: v for k, v in units.items() if v is not None}

        is_practical_only = bool(self.subject and self.subject.is_practical_only)

        if is_practical_only:
            # FIX (requirement #5): store None (not 0.0) for a practical-only
            # subject's semester exam so semester_exam_display correctly
            # renders "N/A" instead of a numeric 0.
            self.semester_exam_marks = None
            self.weakest_unit = "N/A"
            self.strongest_unit = "N/A"
        elif valid_units:
            self.semester_exam_marks = sum(valid_units.values())
            min_score = min(valid_units.values())
            max_score = max(valid_units.values())
            self.weakest_unit = ", ".join([k for k, v in valid_units.items() if v == min_score])
            self.strongest_unit = ", ".join([k for k, v in valid_units.items() if v == max_score])
        else:
            # Theory subject with no unit marks entered yet — genuinely 0,
            # not "N/A" (there IS a theory exam, it just hasn't been scored).
            self.semester_exam_marks = 0.0
            self.weakest_unit = "N/A"
            self.strongest_unit = "N/A"

        self.total_internal_marks = (i_marks or 0.0) + (a_marks or 0.0) + (pr_marks or 0.0)

        # Requirement #4: total combined score = whichever components exist,
        # summed. calculated_total covers internal/assignment/presentation/
        # practical; semester_exam_marks covers the unit-based theory exam
        # (0 when N/A-practical, since practical subjects have no theory
        # component to add).
        self.total_marks = self.calculated_total + (self.semester_exam_marks or 0.0)

        max_possible = self.subject.computed_total_max if self.subject else 100.0

        if max_possible > 0:
            self.percentage = round((self.total_marks / max_possible) * 100, 2)
        else:
            self.percentage = 0.0

        # FIX (requirement #3): grade now comes from the single centralized
        # calculate_grade() function instead of an inline threshold chain
        # that used a DIFFERENT scale (85/75/60/50/40) than the one
        # specified. FIX (requirement #4): result status is strictly
        # PASS/FAIL on the total score via calculate_result_status(), and
        # a FAIL always shows grade 'F' regardless of what calculate_grade
        # would otherwise compute from a sub-40 score (they already agree,
        # but this makes the rule explicit rather than incidental).
        self.result_status = calculate_result_status(self.percentage)
        if self.result_status == 'FAIL':
            self.grade = 'F'
        else:
            self.grade = calculate_grade(self.percentage)

        super().save(*args, **kwargs)


# =========================================================
# 4. SUBJECT-WISE ATTENDANCE MODEL
# =========================================================
class SubjectAttendance(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='subject_attendances')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    semester = models.IntegerField(default=1)

    theory_total = models.IntegerField(default=0)
    theory_attended = models.IntegerField(default=0)
    practical_total = models.IntegerField(default=0)
    practical_attended = models.IntegerField(default=0)

    # Track which Excel batch created/updated this attendance row
    excel_batch = models.ForeignKey('ExcelBatch', null=True, blank=True, on_delete=models.SET_NULL, related_name='attendance_batch')

    class Meta:
        unique_together = ('student', 'subject', 'semester')

    @property
    def theory_percentage(self):
        if self.theory_total > 0:
            return round((self.theory_attended / self.theory_total) * 100, 1)
        return None

    @property
    def practical_percentage(self):
        if self.practical_total > 0:
            return round((self.practical_attended / self.practical_total) * 100, 1)
        return None

    @property
    def total_attended(self):
        return self.theory_attended + self.practical_attended

    @property
    def total_classes_conducted(self):
        return self.theory_total + self.practical_total

    @property
    def overall_subject_percentage(self):
        if self.total_classes_conducted > 0:
            return round((self.total_attended / self.total_classes_conducted) * 100, 1)
        return 0.0

    @property
    def attendance_status(self):
        pct = self.overall_subject_percentage
        if self.total_classes_conducted == 0:
            return {'label': 'N/A', 'color': 'secondary', 'icon': 'bi-dash-circle'}
        elif pct < 75.0:
            return {'label': 'Shortage', 'color': 'danger', 'icon': 'bi-exclamation-octagon-fill'}
        elif 75.0 <= pct < 80.0:
            return {'label': 'Borderline', 'color': 'warning text-dark', 'icon': 'bi-exclamation-triangle-fill'}
        else:
            return {'label': 'Good', 'color': 'success', 'icon': 'bi-check-circle-fill'}

    def __str__(self):
        return f"{self.student.roll_number} - {self.subject.name}: {self.overall_subject_percentage}%"


# =========================================================
# 5. USER PROFILE MODEL
# =========================================================
class UserProfile(models.Model):
    class Role(models.TextChoices):
        TEACHER = "TEACHER", "Teacher"
        STUDENT = "STUDENT", "Student"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)
    # NOTE for anyone editing views.py/admin.py: the reverse accessor from a
    # Student back to this profile is `student.user_account` — NOT
    # `student.userprofile` and NOT `student.profile`. Getting this wrong
    # is what silently broke password reset / login lookups for students
    # (views.py's _get_profile_for_student was fixed to use this).
    student = models.OneToOneField(Student, on_delete=models.SET_NULL, null=True, blank=True, related_name='user_account')
    college_email = models.EmailField(unique=True, null=True, blank=True)
    roll_number = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.role}"


# =========================================================
# 6. ACHIEVEMENT MODEL
# =========================================================
class Achievement(models.Model):
    CATEGORY_CHOICES = [
        ('SPORTS', 'Sports'),
        ('ACADEMIC', 'Academic'),
        ('CULTURAL', 'Cultural'),
        ('OTHER', 'Other'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='achievements')
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=100, choices=CATEGORY_CHOICES, default='ACADEMIC')
    description = models.TextField(blank=True)
    date_achieved = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.student.name} - {self.title}"


# =========================================================
# 7. AUTHORIZED TEACHERS (WHITELIST)
# =========================================================
class AllowedTeacher(models.Model):
    email = models.EmailField(unique=True)
    # FIX (requirement #6): help_text="e.g. Prof. Alan Turing" removed.
    # No prefix validation existed on this field before (plain CharField,
    # blank=True) and none has been added — both "Thomas Edison" and
    # "Prof. Thomas Edison" were already accepted and still are.
    name = models.CharField(max_length=100, blank=True)
    is_registered = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.email})" if self.name else self.email


# =========================================================
# 8. EXCEL FILE HISTORY & BATCH TRACKING MODEL
# =========================================================
class ExcelBatch(models.Model):
    filename = models.CharField(max_length=255)
    file = models.FileField(upload_to='excel_batches/', null=True, blank=True)
    academic_year = models.CharField(max_length=50, blank=True, null=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    # Optional helper: number of records processed by this batch
    record_count = models.IntegerField(null=True, blank=True)

    def delete_associated_records(self):
        """
        Delete Marks, SubjectAttendance, Students created by this batch,
        remove saved file, then delete batch — all inside transaction.
        """
        with transaction.atomic():
            # delete marks and attendance rows that reference this batch
            Marks.objects.filter(excel_batch=self).delete()
            SubjectAttendance.objects.filter(excel_batch=self).delete()

            # delete students created by this batch (cascade deletes marks/attendance)
            Student.objects.filter(created_in_batch=self).delete()

            # delete stored file if present
            if self.file and os.path.isfile(self.file.path):
                try:
                    os.remove(self.file.path)
                except Exception:
                    pass

            # finally remove the batch row itself
            super().delete()

    # Backwards compatibility alias for templates expecting file_name
    @property
    def file_name(self):
        return self.filename

    # Backwards compatibility alias for year_scope
    @property
    def year_scope(self):
        return self.academic_year or ''

    def delete(self, *args, **kwargs):
        # remove file if present before delete
        if self.file and os.path.isfile(self.file.path):
            try:
                os.remove(self.file.path)
            except Exception:
                pass
        super().delete(*args, **kwargs)

    def __str__(self):
        return self.filename


# NOTE: Student account-provisioning signals (post_save/post_delete) used
# to live here. They've been moved to students/signals.py, consolidated
# alongside the AllowedTeacher-deletion signal, so all signal handlers live
# in one place. See signals.py.