import re
import pandas as pd


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

    # M.Sc. Part I (FMCS)
    if clean_roll.startswith(('FMCS', 'MFCS', 'MFC', 'M1')):
        return 'FMCS', 'PART1', 'MSC1'

    # M.Sc. Part II (SMCS)
    elif clean_roll.startswith(('SMCS', 'MSCS', 'SMC', 'M2', 'M3')):
        return 'SMCS', 'PART2', 'MSC2'

    # B.Sc. Computer Science Courses
    elif clean_roll.startswith(('FYCS', 'FCS', 'FC', 'FY', 'F')):
        return 'BSC', 'FY', 'FY'
    elif clean_roll.startswith(('SYCS', 'SCS', 'SC', 'SY', 'S')):
        return 'BSC', 'SY', 'SY'
    elif clean_roll.startswith(('TYCS', 'TCS', 'TC', 'TY', 'T')):
        return 'BSC', 'TY', 'TY'

    return 'BSC', 'FY', 'FY'


def calculate_department_attendance(attendance_queryset):
    """
    Returns 0.0 if dataset or attendance records are empty,
    else calculates average attendance percentage.
    """
    from django.db.models import Avg
    if not attendance_queryset.exists():
        return 0.0

    avg_att = attendance_queryset.aggregate(Avg('attendance_percentage'))['attendance_percentage__avg']
    return round(avg_att, 1) if avg_att is not None else 0.0


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
    Parses a multi-sheet Excel file:
    Sheet 1: Subject_Structure
    Sheet 2: Student_Marks
    Sheet 3: Attendance (Overall or Subject-Wise Matrix)
    """
    from django.db import transaction
    from django.db.models import Avg
    from .models import Student, Subject, Marks, Attendance, SubjectAttendance

    excel_file = pd.ExcelFile(file_path)

    with transaction.atomic():
        # 1. PROCESS SHEET 1: Subject_Structure
        struct_sheet = [s for s in excel_file.sheet_names if 'STRUCTURE' in s.upper() or 'SUBJECT' in s.upper()]
        if struct_sheet:
            df_struct = pd.read_excel(file_path, sheet_name=struct_sheet[0])
            df_struct = df_struct.rename(columns=lambda x: COLUMN_DICTIONARY.get(normalize_header(x), x))

            for _, row in df_struct.iterrows():
                sub_name = str(row.get('subject', '')).strip()
                if not sub_name or pd.isna(sub_name):
                    continue

                Subject.objects.update_or_create(
                    name=sub_name,
                    defaults={
                        'subject_type': str(row.get('subject_type', 'Theory + Practical')),
                        'total_max_marks': clean_num(row.get('total_max_marks')) or 100.0,
                        'max_theory_marks': clean_num(row.get('max_theory_marks')) or 0.0,
                        'max_practical_marks': clean_num(row.get('max_practical_marks')) or 0.0,
                        'max_internal_marks': clean_num(row.get('max_internal_marks')) or 0.0,
                        'max_assignment_marks': clean_num(row.get('max_assignment_marks')) or 0.0,
                        'max_presentation_marks': clean_num(row.get('max_presentation_marks')) or 0.0,
                        'unit_1_max': clean_num(row.get('unit_1_max')) or 0.0,
                        'unit_2_max': clean_num(row.get('unit_2_max')) or 0.0,
                        'unit_3_max': clean_num(row.get('unit_3_max')) or 0.0,
                        'unit_4_max': clean_num(row.get('unit_4_max')) or 0.0,
                    }
                )

        # Cache subjects for lookup
        subject_lookup = {s.name: s for s in Subject.objects.all()}

        # 2. PROCESS SHEET 2: Student_Marks
        marks_sheet = [s for s in excel_file.sheet_names if 'MARKS' in s.upper() or 'STUDENT' in s.upper()]
        if marks_sheet:
            df_marks = pd.read_excel(file_path, sheet_name=marks_sheet[0])
            df_marks = df_marks.rename(columns=lambda x: COLUMN_DICTIONARY.get(normalize_header(x), x))

            for _, row in df_marks.iterrows():
                roll_no = str(row.get('roll_number', '')).strip()
                student_name = str(row.get('name', '')).strip()
                sub_name = str(row.get('subject', '')).strip()

                if not roll_no or not sub_name or pd.isna(roll_no) or pd.isna(sub_name):
                    continue

                prog, part, year = parse_msc_details(roll_no)

                student, _ = Student.objects.update_or_create(
                    roll_number=roll_no,
                    defaults={
                        'name': student_name or roll_no,
                        'programme': prog,
                        'part': part,
                        'year': year
                    }
                )
                
                subject = subject_lookup.get(sub_name)
                if not subject:
                    subject = Subject.objects.create(name=sub_name)
                    subject_lookup[sub_name] = subject

                Marks.objects.update_or_create(
                    student=student,
                    subject=subject,
                    semester=int(clean_num(row.get('semester')) or 1),
                    defaults={
                        'unit_1_marks': clean_num(row.get('unit_1_marks')),
                        'unit_2_marks': clean_num(row.get('unit_2_marks')),
                        'unit_3_marks': clean_num(row.get('unit_3_marks')),
                        'unit_4_marks': clean_num(row.get('unit_4_marks')),
                        'practical_marks': clean_num(row.get('max_practical_marks') or row.get('practical_marks')),
                        'internal_marks': clean_num(row.get('max_internal_marks') or row.get('internal_marks')),
                        'assignment_marks': clean_num(row.get('max_assignment_marks') or row.get('assignment_marks')),
                        'presentation_marks': clean_num(row.get('max_presentation_marks') or row.get('presentation_marks')),
                    }
                )

        # Cache students for lookup
        student_lookup = {s.roll_number: s for s in Student.objects.all()}

        # 3. PROCESS SHEET 3: Attendance (Supports Single Attendance Column or Subject Matrix)
        att_sheet = [s for s in excel_file.sheet_names if 'ATTENDANCE' in s.upper()]
        if att_sheet:
            df_att = pd.read_excel(file_path, sheet_name=att_sheet[0])
            cols = [str(c).strip() for c in df_att.columns]

            is_subject_matrix = any(c in subject_lookup for c in cols)

            for _, row in df_att.iterrows():
                roll_no = str(row.get('roll_number', '') or row.get('Roll No', '')).strip()
                if not roll_no or pd.isna(roll_no):
                    continue

                student = student_lookup.get(roll_no)
                if not student:
                    student, _ = Student.objects.get_or_create(
                        roll_number=roll_no,
                        defaults={'name': str(row.get('name', roll_no)).strip()}
                    )
                    student_lookup[roll_no] = student

                sem = int(clean_num(row.get('semester')) or 1)

                if is_subject_matrix:
                    for col in cols:
                        if col in subject_lookup:
                            att_pct = clean_num(row.get(col))
                            if att_pct is not None:
                                SubjectAttendance.objects.update_or_create(
                                    student=student,
                                    subject=subject_lookup[col],
                                    semester=sem,
                                    defaults={'attendance_percentage': min(max(att_pct, 0.0), 100.0)}
                                )
                    
                    sub_atts = SubjectAttendance.objects.filter(student=student, semester=sem)
                    if sub_atts.exists():
                        overall_pct = round(sub_atts.aggregate(Avg('attendance_percentage'))['attendance_percentage__avg'], 2)
                        Attendance.objects.update_or_create(
                            student=student,
                            semester=sem,
                            defaults={'attendance_percentage': overall_pct}
                        )
                else:
                    att_val = clean_num(row.get('attendance'))
                    if att_val is not None:
                        Attendance.objects.update_or_create(
                            student=student,
                            semester=sem,
                            defaults={'attendance_percentage': min(max(att_val, 0.0), 100.0)}
                        )

    return True, "Data successfully processed."


def analyze_student_performance(marks_obj, attendance_pct=100.0):
    """Calculates performance risk dynamically strictly against defined structure."""
    if not marks_obj:
        return {
            'fail_prob': 0,
            'risk_level': 'STABLE',
            'badge_class': 'success',
            'remedial_plan': 'No evaluation data available.',
            'weakest_unit': 'N/A'
        }

    overall_pct = getattr(marks_obj, 'percentage', 0.0)
    subj = marks_obj.subject

    # Unit Performance Analysis
    units = {
        'Unit 1': (marks_obj.unit_1_marks, subj.unit_1_max if subj else 12.5),
        'Unit 2': (marks_obj.unit_2_marks, subj.unit_2_max if subj else 12.5),
        'Unit 3': (marks_obj.unit_3_marks, subj.unit_3_max if subj else 12.5),
        'Unit 4': (marks_obj.unit_4_marks, subj.unit_4_max if subj else 12.5),
    }
    
    valid_units = [(k, (v[0] / v[1]) * 100) for k, v in units.items() if v[1] and v[1] > 0 and v[0] is not None]

    if valid_units:
        weakest_unit_name, weakest_val = min(valid_units, key=lambda x: x[1])
        remedial_plan = f"Assign practice sheets for {weakest_unit_name} (Score: {round(weakest_val, 1)}%)."
    else:
        weakest_unit_name = "N/A"
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
        'weakest_unit': weakest_unit_name,
        'risk_level': risk_level,
        'badge_class': badge_class
    }


def generate_ai_parent_notice(student_name, roll_no, subject_name, avg_marks, attendance, risk_level):
    """
    Generates an encouraging parent notice supporting both high performers and struggling students.
    """
    salutation = f"Dear Parent / Guardian of {student_name} (Roll No: {roll_no}),"

    # SECTION 1: ATTENDANCE APPRECIATION & GUIDANCE
    if attendance >= 90:
        attendance_msg = f"🌟 Outstanding Attendance: {attendance}%! {student_name}'s dedication to showing up daily is commendable."
    elif attendance >= 75:
        attendance_msg = f"👍 Good Attendance: {attendance}% (Meeting requirement)."
    else:
        attendance_msg = f"💡 Attendance Guidance: Current attendance is {attendance}% (Required: 75%). Regular attendance will help build concept clarity."

    # SECTION 2: ACADEMIC PERFORMANCE & HOPEFUL GUIDANCE
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
    
    # Search for a 2 to 4 digit sequence at the start or inside the roll number
    match = re.search(r'\d{2,4}', str(roll_number))
    if match:
        year_str = match.group(0)
        if len(year_str) == 4:
            return year_str
        elif len(year_str) == 2:
            return f"20{year_str}"
            
    return "N/A"