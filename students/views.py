import re
import pandas as pd

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Avg, Q, Sum
from django.db import transaction
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User  # <--- FIXED: Added User import

# FIXED: Added AllowedTeacher to the imported models list
from .models import Student, Subject, Marks, SubjectAttendance, YEAR_CHOICES, UserProfile, AllowedTeacher
from .utils import (
    map_dataframe_columns, 
    parse_year_from_roll, 
    analyze_student_performance, 
    generate_ai_parent_notice
)


# =========================================================
# UPDATED AUTHENTICATION & DASHBOARD VIEWS
# =========================================================

def custom_login(request):
    """Handles direct login and detects first-time setup for both Students & Teachers."""
    if request.user.is_authenticated:
        if hasattr(request.user, 'profile') and request.user.profile.role == UserProfile.Role.STUDENT:
            return redirect('students:student_dashboard')
        return redirect('students:analytics_dashboard')

    if request.method == 'POST':
        identifier = request.POST.get('username', '').strip().lower()
        password_input = request.POST.get('password', '')

        # -----------------------------------------------------
        # A. STANDARD LOGIN (If user already created a password)
        # -----------------------------------------------------
        user = authenticate(request, username=identifier, password=password_input)
        
        # Fallback lookup if student logs in using full email instead of roll number
        if user is None and '@' in identifier:
            user_obj = User.objects.filter(email__iexact=identifier).first()
            if not user_obj:
                profile_obj = UserProfile.objects.filter(college_email__iexact=identifier).first()
                if profile_obj:
                    user_obj = profile_obj.user

            if user_obj:
                user = authenticate(request, username=user_obj.username, password=password_input)

        if user is not None:
            # Block registered teachers if they aren't on the CS whitelist
            if hasattr(user, 'profile') and user.profile.role == UserProfile.Role.TEACHER:
                if not AllowedTeacher.objects.filter(email__iexact=user.email).exists() and not user.is_superuser:
                    messages.error(request, "Access Denied: You are not authorized as a CS Department teacher.")
                    return redirect('students:login')

            login(request, user)
            profile, _ = UserProfile.objects.get_or_create(user=user)
            if profile.role == UserProfile.Role.STUDENT:
                return redirect('students:student_dashboard')
            return redirect('students:analytics_dashboard')

        # -----------------------------------------------------
        # B. FIRST-TIME SETUP DETECTOR (STUDENTS & TEACHERS)
        # -----------------------------------------------------
        
        # 1. Check if identifier is an ALLOWED CS TEACHER
        allowed_teacher = AllowedTeacher.objects.filter(email__iexact=identifier).first()
        if allowed_teacher:
            teacher_user_exists = User.objects.filter(email__iexact=identifier).exists()
            if not teacher_user_exists or not allowed_teacher.is_registered:
                request.session['setup_email'] = identifier
                request.session['setup_role'] = 'TEACHER'
                return redirect('students:first_time_setup')
            else:
                messages.error(request, "Invalid password. Please try again.")
                return render(request, 'login.html')

        # 2. Check if identifier belongs to a VALID PRE-ADDED STUDENT (Email or Roll Number)
        user_identifier = identifier.split('@')[0]
        student_obj = Student.objects.filter(
            Q(roll_number__iexact=identifier) | Q(roll_number__iexact=user_identifier)
        ).first()

        if student_obj:
            student_user_exists = User.objects.filter(
                Q(username__iexact=student_obj.roll_number.lower()) | Q(email__iexact=identifier)
            ).exists()
            
            if not student_user_exists:
                request.session['setup_email'] = identifier if '@' in identifier else f"{student_obj.roll_number.lower()}@college.edu"
                request.session['setup_roll'] = student_obj.roll_number.lower()
                request.session['setup_role'] = 'STUDENT'
                return redirect('students:first_time_setup')
            else:
                messages.error(request, "Invalid password. Please try again.")
                return render(request, 'login.html')

        # 3. REJECT OUTSIDE / UNRECOGNIZED USERS
        messages.error(request, "Access Denied: Unrecognized email or roll number. Only CS Department students and teachers can log in.")

    return render(request, 'login.html')


def first_time_setup(request):
    """First-time password creation screen for both CS Teachers and Students."""
    email = request.session.get('setup_email')
    role = request.session.get('setup_role')
    roll_number = request.session.get('setup_roll')

    if not email or not role:
        messages.error(request, "Session expired or invalid setup attempt.")
        return redirect('students:login')

    if request.method == 'POST':
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, 'first_time_setup.html', {'email': email, 'role': role})

        if len(password) < 6:
            messages.error(request, "Password must be at least 6 characters long.")
            return render(request, 'first_time_setup.html', {'email': email, 'role': role})

        if role == 'TEACHER':
            allowed_teacher = AllowedTeacher.objects.get(email__iexact=email)
            clean_email = email.lower()
            
            user, _ = User.objects.get_or_create(username=clean_email)
            user.email = clean_email
            user.set_password(password)
            user.save()

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = UserProfile.Role.TEACHER
            profile.college_email = clean_email
            profile.save()

            allowed_teacher.is_registered = True
            allowed_teacher.save()

            messages.success(request, "Teacher account setup complete! Logging you in...")

        elif role == 'STUDENT':
            student_obj = Student.objects.get(roll_number__iexact=roll_number)
            
            # FIXED: Forces roll number to lowercase and explicitly assigns user.email
            clean_username = student_obj.roll_number.lower()
            clean_email = email.lower()

            user, _ = User.objects.get_or_create(username=clean_username)
            user.email = clean_email
            user.set_password(password)
            user.save()

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = UserProfile.Role.STUDENT
            profile.student = student_obj
            profile.college_email = clean_email
            profile.roll_number = student_obj.roll_number.lower()
            profile.save()

            messages.success(request, "Student account setup complete! Logging you in...")

        request.session.pop('setup_email', None)
        request.session.pop('setup_role', None)
        request.session.pop('setup_roll', None)

        login(request, user)
        if role == 'STUDENT':
            return redirect('students:student_dashboard')
        return redirect('students:analytics_dashboard')

    return render(request, 'first_time_setup.html', {'email': email, 'role': role})


def custom_logout(request):
    logout(request)
    return redirect('students:login')


@login_required(login_url='students:login')
def student_dashboard(request):
    if hasattr(request.user, 'profile') and request.user.profile.role == UserProfile.Role.TEACHER:
        return redirect('students:analytics_dashboard')

    user_identifier = request.user.username.split('@')[0]
    student = Student.objects.filter(
        Q(roll_number__iexact=request.user.username) | 
        Q(roll_number__iexact=user_identifier)
    ).first()

    context = {
        'student': student,
        'overall_academic_avg': 0.0,
        'overall_att': 0.0,
        'total_subjects_evaluated': 0,
        'subject_performances': [],
        'subject_attendances': [],
    }

    if student:
        student_marks = Marks.objects.filter(student=student).select_related('subject')
        subject_attendances = SubjectAttendance.objects.filter(student=student).select_related('subject')
        overall_att = calculate_overall_attendance(student)

        subject_performances = []
        total_percentage_sum = 0

        for m in student_marks:
            pct = m.percentage
            total_percentage_sum += pct
            ai_analysis = analyze_student_performance(m, overall_att)

            if isinstance(ai_analysis, dict):
                ai_analysis.setdefault('strongest_unit', m.strongest_unit or 'Unit 1')
                ai_analysis.setdefault('weakest_unit', m.weakest_unit or 'Unit 3')
                ai_analysis.setdefault('remedial_plan', 'Assign practice sheets.')

            subject_performances.append({
                'subject': m.subject.name,
                'marks': m,
                'percentage': pct,
                'status': m.result_status,
                'ai': ai_analysis
            })

        subject_count = len(subject_performances)
        overall_academic_avg = round(total_percentage_sum / subject_count, 1) if subject_count else 0.0

        context.update({
            'subject_performances': subject_performances,
            'subject_attendances': subject_attendances,
            'overall_academic_avg': overall_academic_avg,
            'overall_att': overall_att,
            'total_subjects_evaluated': subject_count,
        })

    return render(request, 'student_dashboard.html', context)
# =========================================================
# EXISTING UTILITIES & DASHBOARD LOGIC
# =========================================================

def clean_val(val):
    if pd.isna(val) or val is None or str(val).strip().lower() in ['', 'nan', 'none', 'null']:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def calculate_overall_attendance(student, semester=None):
    qs = SubjectAttendance.objects.filter(student=student)
    if semester:
        qs = qs.filter(semester=semester)
    
    totals = qs.aggregate(
        th_att=Sum('theory_attended'),
        th_tot=Sum('theory_total'),
        pr_att=Sum('practical_attended'),
        pr_tot=Sum('practical_total')
    )
    
    grand_attended = (totals['th_att'] or 0) + (totals['pr_att'] or 0)
    grand_total = (totals['th_tot'] or 0) + (totals['pr_tot'] or 0)

    if grand_total > 0:
        return round((grand_attended / grand_total) * 100, 2)
    return 0.0


def compute_smart_action_status(attendance_pct, academic_avg):
    att_risk = attendance_pct < 75.0
    acad_risk = academic_avg < 50.0

    if att_risk and acad_risk:
        return {"label": "Critical (Both)", "class": "badge-critical"}
    elif att_risk:
        return {"label": "Low Attendance", "class": "badge-att-risk"}
    elif acad_risk:
        return {"label": "Academic Risk", "class": "badge-acad-risk"}
    return {"label": "Good", "class": "badge-good"}


@login_required
def analytics_dashboard(request):
    if hasattr(request.user, 'profile') and request.user.profile.role == UserProfile.Role.STUDENT:
        messages.warning(request, "Access restricted. You have been redirected to your student portal.")
        return redirect('students:student_dashboard')

    if request.method == 'POST' and request.FILES.get('excel_file'):
        uploaded_file = request.FILES['excel_file']

        try:
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)

            df.columns = df.columns.str.strip()
            
            streamlined_cols = {'Roll Number', 'Subject', 'Total Theory', 'Attended Theory', 'Total Practical', 'Attended Practical'}
            if streamlined_cols.issubset(set(df.columns)):
                records_created = 0
                with transaction.atomic():
                    for _, row in df.iterrows():
                        roll = str(row['Roll Number']).strip()
                        if not roll or roll.lower() == 'nan':
                            continue
                        
                        student_obj, _ = Student.objects.get_or_create(
                            roll_number=roll,
                            defaults={'name': f"Student {roll}"}
                        )
                        subj_name = str(row['Subject']).strip()
                        subject_obj, _ = Subject.objects.get_or_create(name=subj_name)

                        SubjectAttendance.objects.update_or_create(
                            student=student_obj,
                            subject=subject_obj,
                            defaults={
                                'theory_total': int(clean_val(row['Total Theory']) or 0),
                                'theory_attended': int(clean_val(row['Attended Theory']) or 0),
                                'practical_total': int(clean_val(row['Total Practical']) or 0),
                                'practical_attended': int(clean_val(row['Attended Practical']) or 0),
                            }
                        )
                        records_created += 1

                messages.success(request, f"Streamlined attendance uploaded for {records_created} records!")
                return redirect('/dashboard/')

            df, missing_cols = map_dataframe_columns(df)
            if missing_cols:
                messages.error(
                    request, 
                    f"Upload Failed! Missing required columns in file: {', '.join(missing_cols)}"
                )
                return redirect('/dashboard/')

            records_created = 0
            with transaction.atomic():
                for _, row in df.iterrows():
                    val_a = str(row['roll_number']).strip()
                    val_b = str(row['name']).strip()
                    sub_name = str(row['subject']).strip()

                    if not re.search(r'\d', val_a) and re.search(r'\d', val_b):
                        name, roll = val_a, val_b
                    else:
                        roll, name = val_a, val_b

                    if not roll or roll.lower() == 'nan':
                        continue

                    sem_val = 1
                    if 'semester' in row and pd.notnull(row['semester']):
                        digits = re.findall(r'\d+', str(row['semester']))
                        sem_val = int(digits[0]) if digits else 1

                    student_obj, created = Student.objects.get_or_create(
                        roll_number=roll,
                        defaults={'name': name}
                    )
                    
                    if not created and student_obj.name != name:
                        student_obj.name = name
                        student_obj.save()

                    u1 = clean_val(row.get('unit_1_marks') if 'unit_1_marks' in row else row.get('Unit 1'))
                    u2 = clean_val(row.get('unit_2_marks') if 'unit_2_marks' in row else row.get('Unit 2'))
                    u3 = clean_val(row.get('unit_3_marks') if 'unit_3_marks' in row else row.get('Unit 3'))
                    u4 = clean_val(row.get('unit_4_marks') if 'unit_4_marks' in row else row.get('Unit 4'))

                    internal = clean_val(row.get('internal') if 'internal' in row else row.get('Internal'))
                    practical = clean_val(row.get('practical') if 'practical' in row else row.get('Practical'))
                    assignment = clean_val(
                        row.get('assignment') or row.get('Assignmnet ') or row.get('presentation') or row.get('Presentation')
                    )

                    sub_type_val = str(row.get('subject_type', 'THEORY')).strip().upper()
                    if 'PRACTICAL' in sub_type_val:
                        sub_type = 'PRACTICAL'
                    elif 'BOTH' in sub_type_val or 'COMBINED' in sub_type_val:
                        sub_type = 'BOTH'
                    else:
                        sub_type = 'THEORY'

                    max_theory = clean_val(row.get('max_theory_marks', row.get('Theory Max'))) or (50.0 if any(x is not None for x in [u1, u2, u3, u4]) else 0.0)
                    max_pract = clean_val(row.get('max_practical_marks', row.get('Practical Max'))) or (50.0 if (practical is not None and max_theory == 0) else (25.0 if practical is not None else 0.0))
                    max_int = clean_val(row.get('max_internal_marks', row.get('Internal Max'))) or (10.0 if internal is not None else 0.0)
                    max_ass = clean_val(row.get('max_assignment_marks', row.get('Assignment Max'))) or (15.0 if assignment is not None else 0.0)

                    subject_obj, _ = Subject.objects.get_or_create(
                        name=sub_name,
                        defaults={
                            'subject_type': sub_type,
                            'max_theory_marks': max_theory,
                            'max_practical_marks': max_pract,
                            'max_internal_marks': max_int,
                            'max_assignment_marks': max_ass,
                        }
                    )

                    Marks.objects.update_or_create(
                        student=student_obj,
                        subject=subject_obj,
                        semester=sem_val,
                        defaults={
                            'unit_1_marks': u1,
                            'unit_2_marks': u2,
                            'unit_3_marks': u3,
                            'unit_4_marks': u4,
                            'internal_marks': internal,
                            'practical_marks': practical,
                            'assignment_marks': assignment,
                        }
                    )

                    th_att = clean_val(row.get('theory_attended', row.get('Theory Attended')))
                    th_tot = clean_val(row.get('theory_total', row.get('Theory Total')))
                    pr_att = clean_val(row.get('practical_attended', row.get('Practical Attended')))
                    pr_tot = clean_val(row.get('practical_total', row.get('Practical Total')))

                    if any(v is not None for v in [th_att, th_tot, pr_att, pr_tot]):
                        SubjectAttendance.objects.update_or_create(
                            student=student_obj,
                            subject=subject_obj,
                            semester=sem_val,
                            defaults={
                                'theory_attended': th_att or 0,
                                'theory_total': th_tot or 0,
                                'practical_attended': pr_att or 0,
                                'practical_total': pr_tot or 0,
                            }
                        )

                    records_created += 1

            messages.success(request, f"Success! Imported/Updated {records_created} student records.")
            return redirect('/dashboard/')

        except Exception as e:
            messages.error(request, f"Error processing file: {str(e)}")
            return redirect('/dashboard/')

    selected_student_id = request.GET.get('student_id') or request.GET.get('dossier')
    search_query = request.GET.get('search', '').strip()
    selected_subject_id = request.GET.get('subject')
    selected_year = request.GET.get('year')

    subjects = Subject.objects.all()

    context = {
        'subjects': subjects,
        'selected_subject_id': selected_subject_id,
        'selected_year': selected_year,
        'years': YEAR_CHOICES,
        'search_query': search_query,
        'is_student_mode': False,
    }

    if selected_student_id or search_query:
        student = None
        if selected_student_id:
            student = Student.objects.filter(Q(id__iexact=selected_student_id) | Q(roll_number__iexact=selected_student_id)).first()
        elif search_query:
            student = Student.objects.filter(
                Q(roll_number__iexact=search_query) | Q(name__icontains=search_query)
            ).first()

        if student:
            context['is_student_mode'] = True
            context['student'] = student

            student_marks = Marks.objects.filter(student=student).select_related('subject')
            subject_attendances = SubjectAttendance.objects.filter(student=student).select_related('subject')
            overall_att = calculate_overall_attendance(student)

            subject_performances = []
            total_percentage_sum = 0
            pass_count = 0

            for m in student_marks:
                pct = m.percentage
                total_percentage_sum += pct
                if m.result_status == 'PASS':
                    pass_count += 1

                unit_scores = {}
                if getattr(m.subject, 'unit_1_max', getattr(m.subject, 'max_unit_1', 0)) > 0 and m.unit_1_marks is not None:
                    unit_scores['Unit 1'] = m.unit_1_marks
                if getattr(m.subject, 'unit_2_max', getattr(m.subject, 'max_unit_2', 0)) > 0 and m.unit_2_marks is not None:
                    unit_scores['Unit 2'] = m.unit_2_marks
                if getattr(m.subject, 'unit_3_max', getattr(m.subject, 'max_unit_3', 0)) > 0 and m.unit_3_marks is not None:
                    unit_scores['Unit 3'] = m.unit_3_marks
                if getattr(m.subject, 'unit_4_max', getattr(m.subject, 'max_unit_4', 0)) > 0 and m.unit_4_marks is not None:
                    unit_scores['Unit 4'] = m.unit_4_marks

                m.strongest_unit = max(unit_scores, key=unit_scores.get) if unit_scores else "N/A"
                m.weakest_unit = min(unit_scores, key=unit_scores.get) if unit_scores else "N/A"

                ai_analysis = analyze_student_performance(m, overall_att)

                subject_performances.append({
                    'subject': m.subject.name,
                    'marks': m,
                    'percentage': pct,
                    'status': m.result_status,
                    'ai': ai_analysis
                })

            subject_count = len(subject_performances)
            overall_academic_avg = round(total_percentage_sum / subject_count, 1) if subject_count else 0.0

            sorted_subs = sorted(subject_performances, key=lambda x: x['percentage'], reverse=True)
            strongest_subject = sorted_subs[0]['subject'] if sorted_subs else "N/A"
            weakest_subject = sorted_subs[-1]['subject'] if sorted_subs else "N/A"
            primary_ai = sorted_subs[-1]['ai'] if sorted_subs else {}

            parent_notice_draft = generate_ai_parent_notice(
                student.name, student.roll_number, weakest_subject, 
                overall_academic_avg, overall_att, primary_ai.get('risk_level', 'STABLE')
            )

            ai_rec_text = (
                f"Student Profile Inspected: {student.name} ({student.roll_number}). "
                f"Overall Mean: {overall_academic_avg}% | Attendance: {overall_att}%. "
                f"Top Performance Domain: '{strongest_subject}'."
            )
            if primary_ai.get('anomaly_detected'):
                ai_rec_text += f" {primary_ai.get('anomaly_msg')}"

            smart_action = compute_smart_action_status(overall_att, overall_academic_avg)

            context.update({
                'subject_performances': subject_performances,
                'subject_attendances': subject_attendances,
                'overall_academic_avg': overall_academic_avg,
                'overall_att': overall_att,
                'smart_action_status': smart_action,
                'strongest_subject': strongest_subject,
                'weakest_subject': weakest_subject,
                'pass_count': pass_count,
                'total_subjects_evaluated': subject_count,
                'student_risk_score': primary_ai.get('fail_prob', 0),
                'student_risk_level': primary_ai.get('risk_level', 'STABLE'),
                'student_badge_class': primary_ai.get('badge_class', 'success'),
                'parent_notice_draft': parent_notice_draft,
                'ai_copilot_recommendation': ai_rec_text,
                'chart_subject_labels': [s['subject'] for s in subject_performances],
                'chart_subject_scores': [s['percentage'] for s in subject_performances],
            })

            return render(request, 'students/dashboard.html', context)

    all_marks_qs = Marks.objects.all().select_related('student', 'subject')
    if selected_year:
        all_marks_qs = all_marks_qs.filter(student__year=selected_year)
    if selected_subject_id:
        all_marks_qs = all_marks_qs.filter(subject_id=selected_subject_id)

    subject_stats = (
        all_marks_qs.values('subject__name')
        .annotate(avg_score=Avg('percentage'))
        .order_by('subject__name')
    )
    subject_names = [item['subject__name'] for item in subject_stats]
    subject_averages = [round(item['avg_score'], 1) for item in subject_stats]

    unit_mastery = [0, 0, 0, 0]
    if all_marks_qs.exists():
        u1_vals = [m.unit_1_marks for m in all_marks_qs if m.unit_1_marks is not None]
        u2_vals = [m.unit_2_marks for m in all_marks_qs if m.unit_2_marks is not None]
        u3_vals = [m.unit_3_marks for m in all_marks_qs if m.unit_3_marks is not None]
        u4_vals = [m.unit_4_marks for m in all_marks_qs if m.unit_4_marks is not None]

        u1_avg = round((sum(u1_vals) / (len(u1_vals) * 12.0)) * 100, 1) if u1_vals else 0.0
        u2_avg = round((sum(u2_vals) / (len(u2_vals) * 12.0)) * 100, 1) if u2_vals else 0.0
        u3_avg = round((sum(u3_vals) / (len(u3_vals) * 12.0)) * 100, 1) if u3_vals else 0.0
        u4_avg = round((sum(u4_vals) / (len(u4_vals) * 14.0)) * 100, 1) if u4_vals else 0.0
        unit_mastery = [u1_avg, u2_avg, u3_avg, u4_avg]

    total_st = Student.objects.filter(year=selected_year).count() if selected_year else Student.objects.count()
    eval_count = all_marks_qs.count()

    passed_evals = sum(1 for m in all_marks_qs if m.result_status == 'PASS')
    pass_rate = round((passed_evals / eval_count * 100), 1) if eval_count else 0
    overall_avg = round(sum(m.percentage for m in all_marks_qs) / eval_count, 1) if eval_count else 0

    all_students_list = Student.objects.filter(year=selected_year) if selected_year else Student.objects.all()
    
    att_scores = [calculate_overall_attendance(st) for st in all_students_list]
    att_avg = round(sum(att_scores) / len(att_scores), 1) if att_scores else 0.0
    att_map = {st.id: calculate_overall_attendance(st) for st in all_students_list}

    student_marks_map = {}
    for mark in all_marks_qs:
        student_marks_map.setdefault(mark.student_id, []).append(mark)

    master_student_roster = []
    for st in all_students_list:
        st_m = student_marks_map.get(st.id, [])
        att_val = att_map.get(st.id, 0.0)
        st_avg = round(sum(m.percentage for m in st_m) / len(st_m), 1) if st_m else getattr(st, 'academic_avg', 0.0)
        
        first_m = st_m[0] if st_m else None
        ai_data = analyze_student_performance(first_m, att_val) if first_m else {
            'fail_prob': 0, 'risk_level': 'STABLE', 'badge_class': 'success', 'remedial_plan': 'Maintain current study routine.'
        }

        action_status = compute_smart_action_status(att_val, st_avg)

        master_student_roster.append({
            'student': st,
            'roll_number': st.roll_number,
            'name': st.name,
            'avg_marks': st_avg,
            'attendance': att_val,
            'action_status': action_status,
            'risk': ai_data['fail_prob'],
            'level': ai_data['risk_level'],
            'badge': ai_data['badge_class'],
            'remedial': ai_data['remedial_plan']
        })

    department_toppers = sorted(master_student_roster, key=lambda x: x['avg_marks'], reverse=True)[:5]
    bottom_remedial_roster = sorted(master_student_roster, key=lambda x: x['risk'], reverse=True)[:5]

    scatter_data = [{'x': item['attendance'], 'y': item['avg_marks'], 'name': item['student'].name} for item in master_student_roster]

    context.update({
        'total_students': total_st,
        'overall_avg_marks': overall_avg,
        'overall_avg_att': att_avg,
        'overall_pass_rate': pass_rate,
        'subject_names': subject_names,
        'subject_averages': subject_averages,
        'unit_mastery': unit_mastery,
        'department_toppers': department_toppers,
        'bottom_remedial_roster': bottom_remedial_roster,
        'master_student_roster': master_student_roster,
        'scatter_data': scatter_data,
        'ai_copilot_recommendation': (
            f"Department Executive Summary: Enrollment of {total_st} students. "
            f"Academic Score: {overall_avg}% | Attendance: {att_avg}%. "
            f"Unit Mastery Averages: U1 ({unit_mastery[0]}%), U2 ({unit_mastery[1]}%), U3 ({unit_mastery[2]}%), U4 ({unit_mastery[3]}%)."
        ),
    })

    return render(request, 'students/dashboard.html', context)


# =========================================================
# MULTI-SHEET EXCEL BULK INGESTION VIEW
# =========================================================
@login_required
def upload_excel_view(request):
    if hasattr(request.user, 'profile') and request.user.profile.role == UserProfile.Role.STUDENT:
        messages.error(request, "Access denied. Students cannot upload sheets.")
        return redirect('student_dashboard')

    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']

        try:
            xls = pd.ExcelFile(excel_file)
            sheet_names = xls.sheet_names

            if len(sheet_names) < 3:
                messages.error(request, "Uploaded file must contain at least 3 sheets/tabs.")
                return redirect('students:upload_excel')

            with transaction.atomic():
                def get_num(row, col, default=0.0):
                    val = row.get(col)
                    return float(val) if pd.notna(val) else default

                df_subjects = pd.read_excel(xls, sheet_names[0])
                for _, row in df_subjects.iterrows():
                    subj_name = str(row.get('Subject Name', '')).strip()
                    if not subj_name or pd.isna(subj_name):
                        continue

                    subject, _ = Subject.objects.get_or_create(name=subj_name)
                    subject.subject_type = str(row.get('Subject Type', 'THEORY')).strip().upper()

                    subject.total_max_marks = get_num(row, 'Total Marks', 100.0)
                    subject.max_theory_marks = get_num(row, 'Theory Max', 0.0)
                    subject.max_practical_marks = get_num(row, 'Practical Max', 0.0)
                    subject.max_internal_marks = get_num(row, 'Internal Max', 0.0)
                    subject.max_assignment_marks = get_num(row, 'Assignment Max', 0.0)
                    subject.max_presentation_marks = get_num(row, 'Presentation Max', 0.0)

                    subject.unit_1_max = get_num(row, 'Unit 1 Max', 0.0)
                    subject.unit_2_max = get_num(row, 'Unit 2 Max', 0.0)
                    subject.unit_3_max = get_num(row, 'Unit 3 Max', 0.0)
                    subject.unit_4_max = get_num(row, 'Unit 4 Max', 0.0)
                    subject.save()

                subject_lookup = {s.name: s for s in Subject.objects.all()}

                df_marks = pd.read_excel(xls, sheet_names[1])
                for _, row in df_marks.iterrows():
                    roll = str(row.get('Roll Number', '')).strip()
                    subj_name = str(row.get('Subject Name', '')).strip()
                    if not roll or not subj_name or pd.isna(roll) or pd.isna(subj_name):
                        continue

                    student_name = str(row.get('Student Name', '')).strip()
                    
                    student, _ = Student.objects.get_or_create(
                        roll_number=roll,
                        defaults={'name': student_name or roll}
                    )

                    subject = subject_lookup.get(subj_name)
                    if not subject:
                        subject = Subject.objects.create(name=subj_name)
                        subject_lookup[subj_name] = subject

                    def get_mark(col):
                        val = row.get(col)
                        return float(val) if pd.notna(val) and str(val).strip() != '' else None

                    semester = int(row.get('Semester', 1)) if pd.notna(row.get('Semester')) else 1

                    marks_obj, _ = Marks.objects.get_or_create(
                        student=student,
                        subject=subject,
                        semester=semester
                    )

                    marks_obj.unit_1_marks = get_mark('Unit 1')
                    marks_obj.unit_2_marks = get_mark('Unit 2')
                    marks_obj.unit_3_marks = get_mark('Unit 3')
                    marks_obj.unit_4_marks = get_mark('Unit 4')

                    marks_obj.practical_marks = get_mark('Practical')
                    marks_obj.internal_marks = get_mark('Internal')
                    marks_obj.assignment_marks = get_mark('Assignment')
                    marks_obj.presentation_marks = get_mark('Presentation')
                    
                    marks_obj.save()

                student_lookup = {s.roll_number: s for s in Student.objects.all()}

                df_att = pd.read_excel(xls, sheet_names[2])

                for _, row in df_att.iterrows():
                    roll = str(row.get('Roll Number', '') or row.get('Roll No', '')).strip()
                    subj_name = str(row.get('Subject Name', '') or row.get('Subject', '')).strip()
                    if not roll or not subj_name or pd.isna(roll) or pd.isna(subj_name):
                        continue

                    student = student_lookup.get(roll)
                    if not student:
                        student, _ = Student.objects.get_or_create(
                            roll_number=roll,
                            defaults={'name': str(row.get('Name', roll)).strip()}
                        )
                        student_lookup[roll] = student

                    subject = subject_lookup.get(subj_name)
                    if not subject:
                        subject = Subject.objects.create(name=subj_name)
                        subject_lookup[subj_name] = subject

                    sem = int(row.get('Semester', 1)) if pd.notna(row.get('Semester')) else 1

                    th_att = clean_val(row.get('Theory Attended', 0)) or 0
                    th_tot = clean_val(row.get('Theory Total', 0)) or 0
                    pr_att = clean_val(row.get('Practical Attended', 0)) or 0
                    pr_tot = clean_val(row.get('Practical Total', 0)) or 0

                    SubjectAttendance.objects.update_or_create(
                        student=student,
                        subject=subject,
                        semester=sem,
                        defaults={
                            'theory_attended': th_att,
                            'theory_total': th_tot,
                            'practical_attended': pr_att,
                            'practical_total': pr_tot,
                        }
                    )

            messages.success(request, "Success! Multi-sheet academic dataset imported seamlessly.")
            return redirect('students:analytics_dashboard')

        except Exception as e:
            messages.error(request, f"Import error: {str(e)}")

    return render(request, 'students/upload_excel.html')