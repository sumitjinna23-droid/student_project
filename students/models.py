# students/models.py
from django.db import models
from django.contrib.auth.models import User
import os
import logging
from django.db import transaction

logger = logging.getLogger(__name__)

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
    Scale (exact, as specified):
        90.00 - 100.00  -> 'O'
        80.00 - 89.99   -> 'A+'
        70.00 - 79.99   -> 'A'
        60.00 - 69.99   -> 'B+'
        55.00 - 59.99   -> 'B'
        50.00 - 54.99   -> 'C'
        40.00 - 49.99   -> 'D/P'
        below 40.00     -> 'F'
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
    Centralized PASS/FAIL rule: strictly on the total combined score out of
    100. No separate per-component pass/fail.
    """
    if total_score is None:
        return 'FAIL'
    try:
        score = float(total_score)
    except (TypeError, ValueError):
        return 'FAIL'
    return 'PASS' if score >= 40 else 'FAIL'


# =========================================================
# CENTRALIZED STRONGEST/WEAKEST UNIT CALCULATION
# =========================================================
# FIX (strongest/weakest unit bug): this is the single source of truth for
# "which unit is strongest/weakest", used by Marks.save() below, by
# utils.analyze_student_performance(), and by views.analytics_dashboard()'s
# dossier recomputation. Previously there were THREE independent
# implementations:
#   1. Marks.save() here in models.py — compared RAW obtained marks
#      (min/max of u1..u4 directly), never dividing by each unit's own max.
#      This is the actual root cause: Unit 4 = 11 raw > Unit 3 = 10 raw, so
#      it always picked Unit 4, even though Unit 3's percentage (83.3%) beats
#      Unit 4's (78.6%) because Unit 4's max (14) is higher than Unit 3's (12).
#   2. utils.analyze_student_performance() — already correctly percentage-
#      based in your latest version, but duplicated the logic independently
#      and only returned a 'weakest_unit' key (never 'strongest_unit').
#   3. views.py's analytics_dashboard() dossier block — also already
#      correctly percentage-based independently, masking bug #1 for
#      TEACHERS (who see this recomputed value) while leaving it exposed
#      for STUDENTS (whose dashboard falls back to the raw m.strongest_unit
#      field set by bug #1, since analyze_student_performance never
#      supplied a 'strongest_unit' key for the setdefault() to skip).
#
# All three now route through this one function so they can never diverge
# again.
UNIT_MAX_FIELD_MAP = {
    'Unit 1': 'unit_1_max',
    'Unit 2': 'unit_2_max',
    'Unit 3': 'unit_3_max',
    'Unit 4': 'unit_4_max',
}


def compute_unit_strength(subject, unit_marks, debug_label=None):
    """
    subject: a Subject instance (or None) — read via UNIT_MAX_FIELD_MAP,
        i.e. subject.unit_1_max / unit_2_max / unit_3_max / unit_4_max.
        These are the ONLY attribute names used for unit maxima anywhere
        in this codebase now — the old `max_unit_1`-style fallback guesses
        in views.py/utils.py were never real fields and have been removed.
    unit_marks: dict like {'Unit 1': 8.0, 'Unit 2': 9.0, 'Unit 3': 10.0,
        'Unit 4': 11.0} — obtained marks, may include None values for
        units with no recorded score (those are skipped, not treated as 0).
    debug_label: optional string (e.g. "FCS001 / Data Structures / sem 1")
        included in the debug log line, per requirement #2 ("print/log the
        calculated percentages for debugging").

    Returns (strongest_str, weakest_str, percentages_dict):
      - strongest_str / weakest_str: comma-joined unit names, e.g.
        "Unit 3" or "Unit 2, Unit 3" if tied. "N/A" if no unit had both a
        recorded mark and a positive max.
      - percentages_dict: {'Unit 1': 66.67, ...} for logging/inspection.

    Percentage is computed strictly as (obtained / max_marks) * 100.0 —
    no hardcoded fallback divisor (the old utils.py used `12.5` as a
    default when a subject was missing, which silently corrupted results
    for any subject actually using a 14-point max, exactly as in this
    bug report). A missing/zero max simply excludes that unit rather than
    guessing a number.

    Ties are detected with a small float tolerance (1e-5) rather than
    exact equality, and ALL tied units are joined with ", " — never just
    the first or last one found.
    """
    percentages = {}
    for label, obtained in (unit_marks or {}).items():
        if obtained is None:
            continue
        max_field = UNIT_MAX_FIELD_MAP.get(label)
        max_marks = getattr(subject, max_field, 0) if (subject and max_field) else 0
        if not max_marks or max_marks <= 0:
            continue
        percentages[label] = (float(obtained) / float(max_marks)) * 100.0

    if debug_label:
        logger.debug("Unit percentages for %s: %s", debug_label, percentages)

    if not percentages:
        return "N/A", "N/A", percentages

    max_score = max(percentages.values())
    min_score = min(percentages.values())

    strongest = sorted(u for u, v in percentages.items() if abs(v - max_score) < 1e-5)
    weakest = sorted(u for u, v in percentages.items() if abs(v - min_score) < 1e-5)

    return ", ".join(strongest), ", ".join(weakest), percentages


# =========================================================
# 1. STUDENT MODEL
# =========================================================
class Student(models.Model):
    name = models.CharField(max_length=100, default='Student')
    roll_number = models.CharField(max_length=50, unique=True)

    # Independent Programme and Academic Part Tracking
    programme = models.CharField(max_length=50, choices=PROGRAMME_CHOICES, default='BSC')
    part = models.CharField(max_length=50, choices=PART_CHOICES, default='FY')
    year = models.CharField(max_length=50, choices=YEAR_CHOICES, default='FY')

    # Batch-tracking: which ExcelBatch created this student (nullable)
    created_in_batch = models.ForeignKey('ExcelBatch', null=True, blank=True, on_delete=models.SET_NULL, related_name='created_students')

    def auto_assign_year_from_roll(self):
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
            self.programme = 'BSC'
            self.part = 'FY'
            self.year = 'FY'

    def save(self, *args, **kwargs):
        self.auto_assign_year_from_roll()

        if self.roll_number:
            self.roll_number = str(self.roll_number).strip().upper()

        if not self.name or self.name.strip() == '':
            self.name = f"Student {self.roll_number}"
        super().save(*args, **kwargs)

    @classmethod
    def get_or_create_from_roll(cls, roll_number, name=None):
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
        attendances = self.subject_attendances.all()
        total_conducted = sum(a.total_classes_conducted for a in attendances)
        total_attended = sum(a.total_attended for a in attendances)
        if total_conducted > 0:
            return round((total_attended / total_conducted) * 100, 1)
        return 0.0

    def calculate_academic_average(self):
        marks_qs = self.marks.all()
        if marks_qs.exists():
            avg_pct = sum(m.percentage for m in marks_qs) / marks_qs.count()
            return round(avg_pct, 1)
        return 0.0

    def get_360_status(self):
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

    semester_exam_marks = models.FloatField(null=True, blank=True)
    total_internal_marks = models.FloatField(null=True, blank=True)
    total_marks = models.FloatField(null=True, blank=True)
    percentage = models.FloatField(default=0.0)
    grade = models.CharField(max_length=50, blank=True)
    result_status = models.CharField(max_length=50, blank=True)

    weakest_unit = models.CharField(max_length=100, blank=True)
    strongest_unit = models.CharField(max_length=100, blank=True)

    excel_batch = models.ForeignKey('ExcelBatch', null=True, blank=True, on_delete=models.SET_NULL, related_name='marks_batch')

    class Meta:
        unique_together = ('student', 'subject', 'semester')

    @property
    def calculated_total(self):
        return (
            (self.internal_marks or 0.0) +
            (self.practical_marks or 0.0) +
            (self.assignment_marks or 0.0) +
            (self.presentation_marks or 0.0)
        )

    @property
    def semester_exam_display(self):
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

        self.practical_marks = p_marks
        self.internal_marks = i_marks
        self.assignment_marks = a_marks
        self.presentation_marks = pr_marks

        units = {'Unit 1': u1, 'Unit 2': u2, 'Unit 3': u3, 'Unit 4': u4}
        valid_units = {k: v for k, v in units.items() if v is not None}

        is_practical_only = bool(self.subject and self.subject.is_practical_only)

        if is_practical_only:
            self.semester_exam_marks = None
            self.weakest_unit = "N/A"
            self.strongest_unit = "N/A"
        elif valid_units:
            self.semester_exam_marks = sum(valid_units.values())

            # FIX (strongest/weakest unit bug, root cause): this used to be
            #   min_score = min(valid_units.values())
            #   max_score = max(valid_units.values())
            #   self.weakest_unit = ", ".join([k for k, v in valid_units.items() if v == min_score])
            #   self.strongest_unit = ", ".join([k for k, v in valid_units.items() if v == max_score])
            # — comparing RAW marks directly, ignoring that each unit can
            # have a different max (Unit 3 out of 12, Unit 4 out of 14).
            # That's exactly why Unit 4 = 11 (raw) beat Unit 3 = 10 (raw)
            # even though Unit 3's percentage (83.3%) is higher than Unit
            # 4's (78.6%). Now delegates to the single centralized,
            # percentage-based, tie-aware compute_unit_strength().
            debug_label = None
            try:
                debug_label = f"{self.student.roll_number} / {self.subject.name} / sem {self.semester}"
            except Exception:
                pass
            strongest_str, weakest_str, _ = compute_unit_strength(
                self.subject, valid_units, debug_label=debug_label
            )
            self.strongest_unit = strongest_str
            self.weakest_unit = weakest_str
        else:
            self.semester_exam_marks = 0.0
            self.weakest_unit = "N/A"
            self.strongest_unit = "N/A"

        self.total_internal_marks = (i_marks or 0.0) + (a_marks or 0.0) + (pr_marks or 0.0)
        self.total_marks = self.calculated_total + (self.semester_exam_marks or 0.0)

        max_possible = self.subject.computed_total_max if self.subject else 100.0

        if max_possible > 0:
            self.percentage = round((self.total_marks / max_possible) * 100, 2)
        else:
            self.percentage = 0.0

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
    role = models.CharField(max_length=50, choices=Role.choices, default=Role.STUDENT)
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
    record_count = models.IntegerField(null=True, blank=True)

    def delete_associated_records(self):
        with transaction.atomic():
            Marks.objects.filter(excel_batch=self).delete()
            SubjectAttendance.objects.filter(excel_batch=self).delete()
            Student.objects.filter(created_in_batch=self).delete()

            if self.file and os.path.isfile(self.file.path):
                try:
                    os.remove(self.file.path)
                except Exception:
                    pass

            super().delete()

    @property
    def file_name(self):
        return self.filename

    @property
    def year_scope(self):
        return self.academic_year or ''

    def delete(self, *args, **kwargs):
        if self.file and os.path.isfile(self.file.path):
            try:
                os.remove(self.file.path)
            except Exception:
                pass
        super().delete(*args, **kwargs)

    def __str__(self):
        return self.filename


# NOTE: Student account-provisioning signals (post_save/post_delete) live
# in students/signals.py, consolidated alongside the AllowedTeacher-deletion
# signal, so all signal handlers live in one place. See signals.py.

from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.contrib.auth.models import User

# -------------------------------------------------------------
# AUTOMATIC USER CLEANUP SIGNALS
# -------------------------------------------------------------

@receiver(post_delete, sender=StudentProfile)
def cleanup_user_on_student_profile_delete(sender, instance, **kwargs):
    """Deletes linked User when StudentProfile is deleted."""
    if instance.user:
        instance.user.delete()

@receiver(post_delete, sender=Student)
def cleanup_user_on_student_delete(sender, instance, **kwargs):
    """Deletes linked User when Student is deleted."""
    user = User.objects.filter(username__iexact=instance.roll_number).first()
    if user:
        user.delete()

@receiver(post_delete, sender=AllowedTeacher)
def cleanup_user_on_teacher_delete(sender, instance, **kwargs):
    """Deletes linked User when AllowedTeacher is deleted."""
    if instance.email:
        user = User.objects.filter(email__iexact=instance.email).first()
        if user:
            user.delete()