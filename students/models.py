from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

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
# 1. STUDENT MODEL
# =========================================================
class Student(models.Model):
    name = models.CharField(max_length=100, default='Student')
    roll_number = models.CharField(max_length=50, unique=True)
    
    # Independent Programme and Academic Part Tracking
    programme = models.CharField(max_length=20, choices=PROGRAMME_CHOICES, default='BSC')
    part = models.CharField(max_length=10, choices=PART_CHOICES, default='FY')
    year = models.CharField(max_length=10, choices=YEAR_CHOICES, default='FY')

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
    grade = models.CharField(max_length=5, blank=True)
    result_status = models.CharField(max_length=10, blank=True)

    weakest_unit = models.CharField(max_length=100, blank=True)
    strongest_unit = models.CharField(max_length=100, blank=True)

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

        units = {'Unit 1': u1, 'Unit 2': u2, 'Unit 3': u3, 'Unit 4': u4}
        valid_units = {k: v for k, v in units.items() if v is not None}

        if valid_units:
            self.semester_exam_marks = sum(valid_units.values())
            min_score = min(valid_units.values())
            max_score = max(valid_units.values())
            self.weakest_unit = ", ".join([k for k, v in valid_units.items() if v == min_score])
            self.strongest_unit = ", ".join([k for k, v in valid_units.items() if v == max_score])
        else:
            self.semester_exam_marks = 0.0
            self.weakest_unit = "N/A"
            self.strongest_unit = "N/A"

        self.total_internal_marks = (i_marks or 0.0) + (a_marks or 0.0) + (pr_marks or 0.0)
        self.total_marks = self.calculated_total + (self.semester_exam_marks or 0.0)

        max_possible = self.subject.computed_total_max if self.subject else 100.0

        if max_possible > 0:
            self.percentage = round((self.total_marks / max_possible) * 100, 2)

            if self.percentage >= 85:
                self.grade, self.result_status = 'O', 'PASS'
            elif self.percentage >= 75:
                self.grade, self.result_status = 'A+', 'PASS'
            elif self.percentage >= 60:
                self.grade, self.result_status = 'A', 'PASS'
            elif self.percentage >= 50:
                self.grade, self.result_status = 'B', 'PASS'
            elif self.percentage >= 40:
                self.grade, self.result_status = 'C', 'PASS'
            else:
                self.grade, self.result_status = 'F', 'FAIL'
        else:
            self.percentage = 0.0
            self.grade, self.result_status = 'N/A', 'PENDING'

        super().save(*args, **kwargs)


# =========================================================
# 4. SUBJECT-WISE ATTENDANCE MODEL
# =========================================================
class SubjectAttendance(models.Model):
    """
    Stores subject-specific Theory & Practical attendance counts and calculates percentages.
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='subject_attendances')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    semester = models.IntegerField(default=1)

    # Theory Class Counts
    theory_total = models.IntegerField(default=0)
    theory_attended = models.IntegerField(default=0)

    # Practical Class Counts
    practical_total = models.IntegerField(default=0)
    practical_attended = models.IntegerField(default=0)

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
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='STUDENT')
    student = models.OneToOneField(Student, on_delete=models.SET_NULL, null=True, blank=True, related_name='user_account')

    def __str__(self):
        return f"{self.user.username} ({self.role})"


# =========================================================
# 6. ACHIEVEMENT MODEL
# =========================================================
class Achievement(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='achievements')
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=100, default='Academic')
    date_achieved = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.student.name} - {self.title}"

    from django.contrib.auth.models import User
from django.db import models

# Existing models remain above...

class UserProfile(models.Model):
    class Role(models.TextChoices):
        TEACHER = "TEACHER", "Teacher"
        STUDENT = "STUDENT", "Student"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)
    college_email = models.EmailField(unique=True, null=True, blank=True)
    roll_number = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.role}"

# =========================================================
# 7. AUTHORIZED TEACHERS (WHITELIST FOR TESTING & PRODUCTION)
# =========================================================
class AllowedTeacher(models.Model):
    email = models.EmailField(unique=True, help_text="CS Department teacher email allowed to register")
    name = models.CharField(max_length=100, blank=True)
    is_registered = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.email} ({'Registered' if self.is_registered else 'Pending First Login'})"    