import re
import pandas as pd

# Re-exported here so anything (template filters, serializers, future code)
# that prefers importing from students.utils instead of students.models can
# still reach the single centralized implementations. models.py remains the
# actual source of truth — nothing is redefined here.
from .models import calculate_grade, calculate_result_status, compute_unit_strength  # noqa: F401


def normalize_header(header_name):
    """Clean string: lowercase, remove special characters and spaces."""
    return re.sub(r'[^a-z0-9]', '', str(header_name).strip().lower())


COLUMN_DICTIONARY = {
    'rollnumber': 'roll_number', 'rollno': 'roll_number', 'rno': 'roll_number',
    'studentid': 'roll_number', 'student': 'name', 'studentname': 'name',
    'fullname': 'name', 'name': 'name', 'subject': 'subject',
    'subjectname': 'subject', 'course': 'subject', 'sub': 'subject',
    'subjecttype': 'subject_type', 'subtype': 'subject_type', 'type': 'subject_type',
    'totalmarks': 'total_max_marks', 'maxmarks': 'total_max_marks',
    'theory': 'max_theory_marks', 'practical': 'max_practical_marks',
    'internal': 'max_internal_marks', 'assignment': 'max_assignment_marks',
    'presentation': 'max_presentation_marks',
    'unit1max': 'unit_1_max', 'unit2max': 'unit_2_max', 'unit3max': 'unit_3_max', 'unit4max': 'unit_4_max',
    'unit1': 'unit_1_marks', 'unit2': 'unit_2_marks', 'unit3': 'unit_3_marks', 'unit4': 'unit_4_marks',
    'u1': 'unit_1_marks', 'u2': 'unit_2_marks', 'u3': 'unit_3_marks', 'u4': 'unit_4_marks',
    'attendance': 'attendance', 'att': 'attendance', 'semester': 'semester', 'sem': 'semester'
}


def clean_num(val):
    """Converts cell value to float if valid, else returns None (preserving Blank vs 0)."""
    if pd.isna(val) or str(val).strip() == '' or str(val).strip().upper() == 'BLANK':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def parse_msc_details(roll_number):
    """
    Extracts Programme and Academic Part independently from Roll Number:
    - FMCS... -> Programme: 'FMCS', Part: 'PART1' (M.Sc. Part I)
    - SMCS... -> Programme: 'SMCS', Part: 'PART2' (M.Sc. Part II)
    - FYCS/SYCS/TYCS -> B.Sc. Computer Science (FY/SY/TY)
    """
    if not roll_number or pd.isna(roll_number):
        return 'FMCS', 'PART1', 'MSC1'

    clean_roll = str(roll_number).strip().upper()

    if clean_roll.startswith(('FMCS', 'MFCS', 'MFC', 'M1')):
        return 'FMCS', 'PART1', 'MSC1'
    elif clean_roll.startswith(('SMCS', 'MSCS', 'SMC', 'M2', 'M3')):
        return 'SMCS', 'PART2', 'MSC2'
    elif clean_roll.startswith(('FYCS', 'FCS', 'FC', 'FY', 'F')):
        return 'BSC', 'FY', 'FY'
    elif clean_roll.startswith(('SYCS', 'SCS', 'SC', 'SY', 'S')):
        return 'BSC', 'SY', 'SY'
    elif clean_roll.startswith(('TYCS', 'TCS', 'TC', 'TY', 'T')):
        return 'BSC', 'TY', 'TY'

    return 'BSC', 'FY', 'FY'


def calculate_department_attendance(attendance_queryset):
    """
    DEAD / BROKEN CODE — DO NOT CALL. See prior notes: references a
    nonexistent 'attendance_percentage' field. Not called anywhere.
    """
    raise NotImplementedError(
        "calculate_department_attendance() references a nonexistent "
        "'attendance_percentage' field. This function predates the current "
        "SubjectAttendance schema and was never migrated. See docstring."
    )


def map_dataframe_columns(df):
    """Clean column names and map common CSV/Excel headers to standard model fields."""
    new_column_names = {}

    for orig_col in df.columns:
        norm_col = normalize_header(orig_col)
        mapped_col = COLUMN_DICTIONARY.get(norm_col, orig_col)
        new_column_names[orig_col] = mapped_col

    df = df.rename(columns=new_column_names)

    required_cols = ['roll_number', 'name', 'subject']
    missing_cols = [col for col in required_cols if col not in df.columns]

    return df, missing_cols


def process_multi_sheet_excel(file_path):
    """
    DEAD / BROKEN CODE — DO NOT CALL. See prior notes: references a
    nonexistent 'Attendance' model and duplicates working import logic
    that already lives in views.py.
    """
    raise NotImplementedError(
        "process_multi_sheet_excel() references a nonexistent 'Attendance' "
        "model (only SubjectAttendance exists) and duplicates import logic "
        "that already lives in views.py. See docstring."
    )


def analyze_student_performance(marks_obj, attendance_pct=100.0):
    """
    Calculates performance risk dynamically strictly against defined structure.

    FIX (strongest/weakest unit bug — root causes #1 and #2 from the report):
    - Previously this function computed percentages inline using
      `subj.unit_X_max if subj else 12.5` — that `12.5` hardcoded fallback
      was WRONG for any subject whose actual unit max isn't 12.5 (e.g. a
      14-point Unit 4), silently corrupting the comparison. It also only
      ever returned a 'weakest_unit' key, never 'strongest_unit' — which is
      why the student dashboard's setdefault('strongest_unit', ...) always
      fell back to the raw, un-normalized m.strongest_unit model field
      instead.
    - Now delegates entirely to models.compute_unit_strength(), the same
      function Marks.save() and views.py's dossier block use, so there is
      exactly one implementation of "which unit is strongest/weakest" in
      the whole app. Returns BOTH 'strongest_unit' and 'weakest_unit' now.
    """
    if not marks_obj:
        return {
            'fail_prob': 0,
            'risk_level': 'STABLE',
            'badge_class': 'success',
            'remedial_plan': 'No evaluation data available.',
            'strongest_unit': 'N/A',
            'weakest_unit': 'N/A'
        }

    overall_pct = getattr(marks_obj, 'percentage', 0.0)
    subj = marks_obj.subject

    unit_marks = {
        'Unit 1': marks_obj.unit_1_marks,
        'Unit 2': marks_obj.unit_2_marks,
        'Unit 3': marks_obj.unit_3_marks,
        'Unit 4': marks_obj.unit_4_marks,
    }

    debug_label = None
    try:
        debug_label = f"{marks_obj.student.roll_number} / {subj.name if subj else 'N/A'}"
    except Exception:
        pass

    strongest_unit_name, weakest_unit_name, unit_percentages = compute_unit_strength(
        subj, unit_marks, debug_label=debug_label
    )

    if unit_percentages:
        min_pct = min(unit_percentages.values())
        remedial_plan = f"Assign practice sheets for {weakest_unit_name} (Score: {round(min_pct, 1)}%)."
    else:
        remedial_plan = "Focus on practical lab submissions and continuous assessments."

    if attendance_pct < 75:
        remedial_plan += " Mandatory 1-on-1 counseling required due to low attendance."

    fail_prob = max(0, min(100, round((100 - overall_pct) * 0.65 + (100 - attendance_pct) * 0.35, 1)))

    if fail_prob >= 50 or overall_pct < 40:
        risk_level, badge_class = "CRITICAL RISK", "danger"
    elif fail_prob >= 25 or attendance_pct < 75:
        risk_level, badge_class = "AT RISK", "warning"
    else:
        risk_level, badge_class = "STABLE", "success"

    return {
        'fail_prob': fail_prob,
        'remedial_plan': remedial_plan,
        'strongest_unit': strongest_unit_name,
        'weakest_unit': weakest_unit_name,
        'risk_level': risk_level,
        'badge_class': badge_class
    }


def generate_ai_parent_notice(student_name, roll_no, subject_name, avg_marks, attendance, risk_level):
    """
    Generates an encouraging parent notice supporting both high performers and struggling students.
    """
    salutation = f"Dear Parent / Guardian of {student_name} (Roll No: {roll_no}),"

    if attendance >= 90:
        attendance_msg = f"🌟 Outstanding Attendance: {attendance}%! {student_name}'s dedication to showing up daily is commendable."
    elif attendance >= 75:
        attendance_msg = f"👍 Good Attendance: {attendance}% (Meeting requirement)."
    else:
        attendance_msg = f"💡 Attendance Guidance: Current attendance is {attendance}% (Required: 75%). Regular attendance will help build concept clarity."

    if avg_marks >= 75:
        headline = f"🎉 EXCELLENCE UPDATE: {student_name} is performing brilliantly in '{subject_name}' ({avg_marks}%)!"
        academic_body = f"{student_name}'s hard work, discipline, and understanding in '{subject_name}' are outstanding. Keep up this wonderful momentum!"
        action_step = "• Next Step: Continue taking on challenging problems to master the subject completely."

    elif "CRITICAL" in risk_level or "RISK" in risk_level or avg_marks < 50:
        headline = f"🌱 GROWTH & SUPPORT UPDATE: We see great potential in {student_name} for '{subject_name}' ({avg_marks}%)."
        academic_body = f"We believe every student learns at their own pace. Scoring lower in certain topics is simply a step toward learning—never a limit on what {student_name} can achieve."
        action_step = f"• Action Plan for {subject_name}: We will provide targeted revision exercises and practice sheets to strengthen foundational topics."

    else:
        headline = f"📘 STEADY PROGRESS: {student_name} is maintaining a good foundation in '{subject_name}' ({avg_marks}%)."
        academic_body = f"Effort is steady. With consistent daily review, {student_name} can easily reach top-tier marks."
        action_step = "• Next Step: Focus on practicing past exam questions to boost confidence."

    closing = "\n\nWe are grateful to partner with you in supporting your child's learning journey.\n\nWarm regards,\nDepartment Faculty Team"

    return f"{salutation}\n\n{headline}\n\n{attendance_msg}\n\n{academic_body}\n\n{action_step}{closing}"


def parse_year_from_roll(roll_number):
    """
    Extracts the academic year or batch year from a roll number string.
    Example: '2023CS101' -> '2023' or '23' -> 2nd Year
    """
    if not roll_number:
        return "N/A"

    match = re.search(r'\d{2,4}', str(roll_number))
    if match:
        year_str = match.group(0)
        if len(year_str) == 4:
            return year_str
        elif len(year_str) == 2:
            return f"20{year_str}"

    return "N/A"