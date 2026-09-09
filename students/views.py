# students/views.py
import re
import pandas as pd
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib import messages
from django.db.models import Avg, Q, Sum
from django.db import transaction
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required

# Auth models & permissions
from django.contrib.auth.models import User, Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.apps import apps

from django.urls import reverse
from django.db.models import Q as DjangoQ

# Logging
import logging
logger = logging.getLogger(__name__)

from .models import Student, AllowedTeacher, UserProfile, ExcelBatch
from .models import (
    Student, Subject, Marks, SubjectAttendance, YEAR_CHOICES, UserProfile, AllowedTeacher, Achievement,
    calculate_grade, calculate_result_status, compute_unit_strength,
)
from .utils import (
    map_dataframe_columns,
    parse_year_from_roll,
    generate_ai_parent_notice
)


# =========================================================
# DYNAMIC AI PERFORMANCE ANALYSIS HELPER
# =========================================================

def analyze_student_performance(marks_obj, overall_att=100.0):
    """
    Evaluates student performance across active Unit and Non-Unit components dynamically.
    Returns a consistent dictionary with AI performance metrics, dynamic dynamic remediation message,
    and risk indicators usable across all 4 dashboard views.
    """
    if not marks_obj:
        return {
            'fail_prob': 0,
            'risk_level': 'STABLE',
            'badge_class': 'success',
            'remedial_plan': 'No assessment data available.',
            'remedial_str': 'No assessment data available.',
            'strongest_unit': 'N/A',
            'weakest_unit': 'N/A',
            'anomaly_detected': False,
            'anomaly_msg': ''
        }

    subj = getattr(marks_obj, 'subject', None)
    
    # Resolve Max Marks for each component safely
    u1_max = float(getattr(subj, 'unit_1_max', 0) or getattr(subj, 'max_unit_1', 0) or 0)
    u2_max = float(getattr(subj, 'unit_2_max', 0) or getattr(subj, 'max_unit_2', 0) or 0)
    u3_max = float(getattr(subj, 'unit_3_max', 0) or getattr(subj, 'max_unit_3', 0) or 0)
    u4_max = float(getattr(subj, 'unit_4_max', 0) or getattr(subj, 'max_unit_4', 0) or 0)

    pr_max = float(getattr(subj, 'max_practical_marks', 0) or 0)
    int_max = float(getattr(subj, 'max_internal_marks', 0) or 0)
    ass_max = float(getattr(subj, 'max_assignment_marks', 0) or 0)
    pres_max = float(getattr(subj, 'max_presentation_marks', 0) or 0)

    # Dictionary of all assessment components
    all_components = {
        'Unit 1': (marks_obj.unit_1_marks, u1_max, True),
        'Unit 2': (marks_obj.unit_2_marks, u2_max, True),
        'Unit 3': (marks_obj.unit_3_marks, u3_max, True),
        'Unit 4': (marks_obj.unit_4_marks, u4_max, True),
        'Practical': (marks_obj.practical_marks, pr_max, False),
        'Internal': (marks_obj.internal_marks, int_max, False),
        'Assignment': (marks_obj.assignment_marks, ass_max, False),
        'Presentation': (marks_obj.presentation_marks, pres_max, False),
    }

    unit_percentages = {}
    non_unit_percentages = {}
    critical_components = []

    for comp_name, (score, max_score, is_unit) in all_components.items():
        if score is not None and max_score > 0:
            pct = round((float(score) / float(max_score)) * 100.0, 1)
            if is_unit:
                unit_percentages[comp_name] = pct
            else:
                non_unit_percentages[comp_name] = pct
            
            if pct < 40.0:
                critical_components.append((comp_name, pct))

    # Evaluate Weakest & Strongest Unit Logic
    weakest_unit_str = "None"
    strongest_unit_str = "None"
    min_score_val = None

    if unit_percentages:
        min_score = min(unit_percentages.values())
        max_score = max(unit_percentages.values())

        if min_score == max_score and min_score == 100.0:
            weakest_unit_str = "None"
            strongest_unit_str = ", ".join([u for u, p in unit_percentages.items()])
        elif min_score == max_score:
            weakest_unit_str = "None"
            strongest_unit_str = ", ".join([u for u, p in unit_percentages.items()])
        else:
            weak_units = [u for u, p in unit_percentages.items() if p == min_score]
            strong_units = [u for u, p in unit_percentages.items() if p == max_score]
            weakest_unit_str = ", ".join(weak_units)
            strongest_unit_str = ", ".join(strong_units)
            min_score_val = min_score

    # Determine Academic Remedial Dynamic String
    academic_msg = ""
    
    # Check perfect mastery condition across all active components
    all_units_ok = all(p >= 75.0 for p in unit_percentages.values()) if unit_percentages else True
    all_non_units_ok = all(p >= 75.0 for p in non_unit_percentages.values()) if non_unit_percentages else True
    perfect_academic_mastery = all_units_ok and all_non_units_ok and (weakest_unit_str == "None")

    if len(critical_components) > 1:
        # Multiple critical failures (< 40%)
        names = [comp[0] for comp in critical_components]
        if len(names) == 2:
            critical_components_str = " and ".join(names)
        else:
            critical_components_str = ", ".join(names[:-1]) + f", and {names[-1]}"
        academic_msg = f"Your score in {critical_components_str} is currently below 40%. This area needs more attention and support right now. Don’t be discouraged by your current result. Start with the basics, practice step by step, and ask your teacher for help when you need it. With patience and consistent effort, you can improve."
    
    elif len(critical_components) == 1 and not critical_components[0][0].startswith("Unit"):
        # Single Non-Unit component < 40%
        comp_name, score = critical_components[0]
        academic_msg = f"Your score in {comp_name} is currently {score}%. This area needs more attention and support right now. Don’t be discouraged by your current result. Start with the basics, practice step by step, and ask your teacher for help when you need it. With patience and consistent effort, you can improve."
    
    else:
        # Check single non-unit components between 40% and 75%
        weak_non_units = {k: v for k, v in non_unit_percentages.items() if v < 75.0}
        if weak_non_units:
            first_comp, score = list(weak_non_units.items())[0]
            if score < 40.0:
                academic_msg = f"Your score in {first_comp} is currently {score}%. This area needs more attention and support right now. Don’t be discouraged by your current result. Start with the basics, practice step by step, and ask your teacher for help when you need it. With patience and consistent effort, you can improve."
            else:
                academic_msg = f"Your score in {first_comp} is currently {score}%. You are making progress, but this area needs more practice. Keep working on the topics you find difficult and take time to strengthen your understanding. With regular practice and consistent effort, you can continue to improve."
        elif min_score_val is not None:
            # Weakest Unit specific guidance
            if min_score_val < 40.0:
                academic_msg = f"Your score in {weakest_unit_str} is currently {min_score_val}%. This Unit needs more attention and support right now. Don’t be discouraged. Go back to the basics, take one topic at a time, and practice regularly. Ask your teacher for guidance whenever you need it. With consistent effort, you can strengthen your understanding."
            elif min_score_val < 75.0:
                academic_msg = f"Your score in {weakest_unit_str} is currently {min_score_val}%. You are making progress, but this Unit needs some extra practice. Review the topics you find difficult and keep practicing them. Step by step, you can strengthen your understanding and improve your performance."
            else:
                academic_msg = f"Excellent work! Your score in {weakest_unit_str} is {min_score_val}%, showing strong performance. This is currently your lowest-scoring Unit, but you are still doing well. Continue refining your understanding and building on what you already know. Keep learning, keep growing, and continue giving your best."

    # Determine Attendance Dynamic String
    attendance_msg = ""
    if overall_att < 50.0:
        attendance_msg = f"Your attendance is currently {overall_att}%, which is below the expected level. Missing many classes can make it difficult to keep up with your studies. Try to attend classes more regularly and speak with your teacher if you are facing difficulties. Your current attendance can improve, and it is not too late to make a better start."
    elif overall_att < 75.0:
        attendance_msg = f"Your attendance is currently {overall_att}%. Attending classes more regularly will help you stay on track and avoid missing important lessons. Keep working toward better attendance, because every class you attend gives you another opportunity to learn and grow."

    # Combine Messages
    if perfect_academic_mastery and overall_att >= 75.0:
        remedial_str = "Excellent work! Your marks and attendance show consistent effort, commitment, and dedication. Your hard work is clearly reflected in your performance. Keep learning, keep growing, and continue giving your best. You are on a strong path."
    elif academic_msg and attendance_msg:
        remedial_str = f"{academic_msg} {attendance_msg}"
    elif academic_msg:
        remedial_str = academic_msg
    elif attendance_msg:
        remedial_str = attendance_msg
    else:
        remedial_str = "Excellent work! Your marks and attendance show consistent effort, commitment, and dedication. Your hard work is clearly reflected in your performance. Keep learning, keep growing, and continue giving your best. You are on a strong path."

    # Risk metrics calculation
    overall_pct = getattr(marks_obj, 'percentage', 0.0) or 0.0
    fail_prob = max(0, min(100, int(100 - overall_pct)))
    
    if overall_pct < 40 or overall_att < 50:
        risk_level = 'CRITICAL'
        badge_class = 'danger'
    elif overall_pct < 60 or overall_att < 75:
        risk_level = 'WARNING'
        badge_class = 'warning'
    else:
        risk_level = 'STABLE'
        badge_class = 'success'

    # Dynamic Anomaly Detection Message Logic
    anomaly_detected = (overall_att < 75.0 or overall_pct < 50.0)
    anomaly_msg = ""
    
    if anomaly_detected:
        if overall_att < 75.0 and overall_pct < 50.0:
            anomaly_msg = "Low academic score and low attendance flag detected."
        elif overall_att < 75.0:
            anomaly_msg = "Low attendance flag detected."
        else:
            anomaly_msg = "Low academic score flag detected."

    return {
        'fail_prob': fail_prob,
        'risk_level': risk_level,
        'badge_class': badge_class,
        'remedial_plan': remedial_str,
        'remedial_str': remedial_str,
        'strongest_unit': strongest_unit_str,
        'weakest_unit': weakest_unit_str,
        'anomaly_detected': anomaly_detected,
        'anomaly_msg': anomaly_msg
    }


# =========================================================
# HELPER FUNCTIONS & NAME RESOLUTION
# =========================================================

def get_user_display_name(user):
    """
    Priority resolution:
      - Student Name (from linked profile.student)
      - AllowedTeacher.name (match by email), only if user is authenticated
      - Django User.get_full_name()
      - Cleaned username fallback

    Safe for AnonymousUser.
    """
    try:
        if not user or not getattr(user, 'is_authenticated', False):
            return ''

        profile = _get_profile(user)
        if profile and getattr(profile, 'student', None) and getattr(profile.student, 'name', None):
            return profile.student.name

        if getattr(user, 'is_authenticated', False) and getattr(user, 'email', None):
            user_email = user.email
            teacher_entry = AllowedTeacher.objects.filter(email__iexact=user_email).first()
            if teacher_entry and getattr(teacher_entry, 'name', None):
                return teacher_entry.name.strip()

        full_name = ''
        try:
            full_name = user.get_full_name().strip()
        except Exception:
            full_name = ''
        if full_name:
            return full_name

        username = getattr(user, 'username', '') or ''
        return username.split('@')[0].replace('.', ' ').replace('_', ' ').title()
    except Exception:
        logger.exception("get_user_display_name failed")
        return ''


def _get_profile(user):
    """
    Centralized profile lookup so every view resolves the related UserProfile
    the SAME way, regardless of whether your OneToOneField's related_name is
    'userprofile' or 'profile'.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    return getattr(user, 'userprofile', None) or getattr(user, 'profile', None)


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


def _is_student_role(user):
    profile = _get_profile(user)
    return bool(profile and getattr(profile, 'role', None) == getattr(UserProfile.Role, 'STUDENT', 'STUDENT'))


def _user_is_teacher(user):
    try:
        if not user or not getattr(user, 'is_authenticated', False):
            return False

        if getattr(user, 'is_superuser', False):
            return False

        if _is_student_role(user):
            return False

        profile = _get_profile(user)
        if profile and getattr(profile, 'role', None) == getattr(UserProfile.Role, 'TEACHER', 'TEACHER'):
            return True

        if getattr(user, 'is_staff', False):
            return True

        if user.groups.filter(name__iexact='Teachers').exists():
            return True

        if getattr(user, 'is_authenticated', False) and getattr(user, 'email', None):
            if AllowedTeacher.objects.filter(email__iexact=user.email).exists():
                return True

    except Exception:
        logger.exception("_user_is_teacher check failed")
    return False


def _destination_after_login(user, next_url=None):
    try:
        if not user:
            return 'students:login'

        if getattr(user, 'is_superuser', False) or _user_is_teacher(user):
            if next_url and 'student-dashboard' not in next_url and 'student_dashboard' not in next_url:
                return next_url
            return reverse('students:analytics_dashboard')

        if _is_student_role(user):
            if next_url and 'dashboard' in next_url and 'student' not in next_url:
                return reverse('students:student_dashboard')
            return next_url or reverse('students:student_dashboard')

    except Exception:
        logger.exception("_destination_after_login error")
    return next_url or reverse('students:analytics_dashboard')


# =========================================================
# AUTHENTICATION & PASSWORD RESET VIEWS
# =========================================================
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.db.models import Q
from .models import AllowedTeacher, Student, UserProfile

def custom_login(request):
    """
    Unified login logic:
    - If user has NO password set in DB -> Redirects directly to setup page.
    - If user HAS a password set in DB -> Requires entering and validating the password.
    """
    if request.user.is_authenticated:
        dest = _destination_after_login(request.user, next_url=request.GET.get('next'))
        return redirect(dest)

    next_url = request.GET.get('next') or request.POST.get('next') or None

    if request.method == 'POST':
        identifier = request.POST.get('username', '').strip()
        password_input = request.POST.get('password', '').strip()

        if not identifier:
            messages.error(request, "Enter Email, Roll Number, or Admin Name.")
            return render(request, 'students/login.html', {'next': next_url} if next_url else {})

        # -------------------------------------------------------------
        # 1. TEACHER CHECK (By Email)
        # -------------------------------------------------------------
        if '@' in identifier:
            email = identifier.lower()
            allowed_teacher = AllowedTeacher.objects.filter(email__iexact=email).first()

            if allowed_teacher:
                existing_user = User.objects.filter(email__iexact=email).first()

                # NO USER ACCOUNT OR NO USABLE PASSWORD -> DIRECT TO SETUP
                if not existing_user or not existing_user.has_usable_password():
                    request.session['setup_email'] = email
                    request.session['setup_role'] = 'TEACHER'
                    if getattr(allowed_teacher, 'name', None):
                        request.session['setup_name'] = allowed_teacher.name
                    messages.info(request, "First time logging in? Set up your password below.")
                    return redirect(f"{reverse('students:first_time_setup')}?email={email}&role=TEACHER")

                # PASSWORD EXISTS IN DB -> REQUIRE PASSWORD
                if not password_input:
                    messages.error(request, "Please enter your password.")
                    return render(request, 'students/login.html', {'next': next_url} if next_url else {})

                auth_user = authenticate(request, username=existing_user.username, password=password_input)
                if auth_user and auth_user.is_active:
                    login(request, auth_user)
                    return redirect(_destination_after_login(auth_user, next_url=next_url))
                else:
                    messages.error(request, "Wrong password. Please try again or use 'Forgot Password'.")
                    return render(request, 'students/login.html', {'next': next_url} if next_url else {})

            messages.error(request, f"Access Denied: Email '{email}' is not registered.")
            return render(request, 'students/login.html', {'next': next_url} if next_url else {})

        # -------------------------------------------------------------
        # 2. STUDENT CHECK (By Roll Number)
        # -------------------------------------------------------------
        roll_test = identifier.split('@')[0]
        student = Student.objects.filter(roll_number__iexact=roll_test).first()

        if student:
            profile = _get_profile_for_student(student)
            linked_user = profile.user if (profile and getattr(profile, 'user', None)) else User.objects.filter(username__iexact=student.roll_number).first()

            # NO USER ACCOUNT OR NO USABLE PASSWORD -> DIRECT TO SETUP
            if not linked_user or not linked_user.has_usable_password():
                fallback_email = f"{student.roll_number.lower()}@college.local"
                setup_email = linked_user.email if (linked_user and linked_user.email) else fallback_email
                request.session['setup_email'] = setup_email
                request.session['setup_role'] = 'STUDENT'
                request.session['setup_roll'] = student.roll_number
                messages.info(request, "First time logging in? Set up your password below.")
                return redirect(f"{reverse('students:first_time_setup')}?email={setup_email}&role=STUDENT&roll={student.roll_number}")

            # PASSWORD EXISTS IN DB -> REQUIRE PASSWORD
            if not password_input:
                messages.error(request, "Please enter your password.")
                return render(request, 'students/login.html', {'next': next_url} if next_url else {})

            auth_user = authenticate(request, username=linked_user.username, password=password_input)
            if auth_user and auth_user.is_active:
                login(request, auth_user)
                return redirect(_destination_after_login(auth_user, next_url=next_url))
            else:
                messages.error(request, "Wrong password. Please try again or use 'Forgot Password'.")
                return render(request, 'students/login.html', {'next': next_url} if next_url else {})

        # -------------------------------------------------------------
        # 3. ADMIN CHECK (By Username or Name)
        # -------------------------------------------------------------
        admin_user = User.objects.filter(
            Q(username__iexact=identifier) | Q(first_name__iexact=identifier)
        ).first()

        if admin_user:
            # NO USABLE PASSWORD -> DIRECT TO SETUP
            if not admin_user.has_usable_password():
                admin_email = admin_user.email or f"{admin_user.username}@college.local"
                request.session['setup_email'] = admin_email
                request.session['setup_role'] = 'ADMIN'
                messages.info(request, "First time logging in? Set up your password below.")
                return redirect(f"{reverse('students:first_time_setup')}?email={admin_email}&role=ADMIN")

            # PASSWORD EXISTS IN DB -> REQUIRE PASSWORD
            if not password_input:
                messages.error(request, "Please enter your password.")
                return render(request, 'students/login.html', {'next': next_url} if next_url else {})

            auth_user = authenticate(request, username=admin_user.username, password=password_input)
            if auth_user and auth_user.is_active:
                login(request, auth_user)
                return redirect(_destination_after_login(auth_user, next_url=next_url))
            else:
                messages.error(request, "Wrong password. Please try again or use 'Forgot Password'.")
                return render(request, 'students/login.html', {'next': next_url} if next_url else {})

        # -------------------------------------------------------------
        # 4. USER NOT FOUND
        # -------------------------------------------------------------
        is_roll_number = any(char.isdigit() for char in identifier)
        if is_roll_number:
            messages.error(request, f"No student record found for Roll Number '{identifier}'.")
        else:
            messages.error(request, f"Access denied. User '{identifier}' not found in database.")

        return render(request, 'students/login.html', {'next': next_url} if next_url else {})

    return render(request, 'students/login.html', {'next': next_url} if next_url else {})

def _get_profile_for_student(student):
    if not student:
        return None
    return getattr(student, 'user_account', None)


def first_time_setup(request):
    email = request.session.get('setup_email')
    role = request.session.get('setup_role')
    roll_number = request.session.get('setup_roll')

    if not email:
        email = request.GET.get('email')
    if not role:
        role = request.GET.get('role')
    if not roll_number:
        roll_number = request.GET.get('roll')

    if not email or not role:
        messages.error(request, "Setup session expired or invalid. Please start again from the login page.")
        return redirect('students:login')

    email = email.strip().lower()

    if request.method == 'POST':
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not password or password != confirm_password:
            messages.error(request, "Passwords must match and not be empty.")
            return render(request, 'first_time_setup.html', {'email': email, 'role': role, 'roll': roll_number})

        if len(password) < 6:
            messages.error(request, "Password must be at least 6 characters.")
            return render(request, 'first_time_setup.html', {'email': email, 'role': role, 'roll': roll_number})

        user = None
        profile = None

        try:
            if role.upper() == 'TEACHER':
                allowed_teacher = AllowedTeacher.objects.filter(email__iexact=email).first()
                if not allowed_teacher:
                    messages.error(request, "No teacher found with that email. Contact admin.")
                    return redirect('students:login')

                with transaction.atomic():
                    username = email
                    user, created = User.objects.get_or_create(username=username, defaults={'email': email})
                    user.email = email
                    user.set_password(password)
                    user.is_active = True
                    user.is_staff = True

                    if getattr(allowed_teacher, 'name', None):
                        raw_name = allowed_teacher.name.strip()
                        parts = raw_name.split(None, 1)
                        user.first_name = parts[0]
                        user.last_name = parts[1] if len(parts) > 1 else ''
                    user.save()

                    teachers_group, created_group = Group.objects.get_or_create(name='Teachers')

                    try:
                        allowed_model = apps.get_model('students', 'AllowedTeacher')
                        allowed_model_name = allowed_model._meta.model_name
                    except Exception:
                        allowed_model_name = 'allowedteacher'

                    students_perms = Permission.objects.filter(content_type__app_label='students').exclude(content_type__model=allowed_model_name)

                    if created_group:
                        teachers_group.permissions.set(students_perms)
                    else:
                        existing_ids = set(teachers_group.permissions.values_list('id', flat=True))
                        to_add = [p for p in students_perms if p.id not in existing_ids]
                        if to_add:
                            teachers_group.permissions.add(*to_add)

                    if not user.groups.filter(id=teachers_group.id).exists():
                        user.groups.add(teachers_group)

                    profile, _ = UserProfile.objects.get_or_create(user=user)
                    profile.role = UserProfile.Role.TEACHER
                    profile.college_email = email
                    profile.save()

                    allowed_teacher.is_registered = True
                    allowed_teacher.save()

                messages.success(request, "Teacher account setup complete. Logging you in...")

            else:
                student_obj = Student.objects.filter(roll_number__iexact=roll_number).first()
                if not student_obj:
                    messages.error(request, "Student record not found. Contact admin.")
                    return redirect('students:login')

                with transaction.atomic():
                    username = student_obj.roll_number.lower()
                    user, created = User.objects.get_or_create(username=username, defaults={'email': email})
                    user.email = email
                    user.set_password(password)
                    user.is_active = True
                    user.save()

                    profile, _ = UserProfile.objects.get_or_create(user=user)
                    profile.role = UserProfile.Role.STUDENT
                    profile.student = student_obj
                    profile.college_email = email
                    profile.roll_number = student_obj.roll_number.lower()
                    profile.save()

                messages.success(request, "Student account setup complete. Logging you in...")

        except Exception:
            logger.exception("first_time_setup failed for role=%s email=%s", role, email)
            messages.error(request, "Something went wrong completing setup. Please try again or contact admin.")
            return redirect('students:login')

        request.session.pop('setup_email', None)
        request.session.pop('setup_role', None)
        request.session.pop('setup_roll', None)

        username_for_auth = user.username
        authed = authenticate(request, username=username_for_auth, password=password)

        if authed:
            login(request, authed)
            dest = _destination_after_login(authed)
            return redirect(dest)
        else:
            try:
                user.backend = 'django.contrib.auth.backends.ModelBackend'
                login(request, user)
                dest = _destination_after_login(user)
                return redirect(dest)
            except Exception:
                messages.warning(request, "Account created but automatic login failed. Please login manually.")
                return redirect('students:login')

    return render(request, 'first_time_setup.html', {'email': email, 'role': role, 'roll': roll_number})


def password_reset_request(request):
    if request.method == "POST":
        input_value = request.POST.get('username_or_email', '').strip()
        if not input_value:
            messages.error(request, "Please enter Admin Full Name, Email Address, or Roll Number.")
            return render(request, 'students/password_reset_request.html')

        from django.db.models.functions import Concat
        from django.db.models import Value, CharField

        user = User.objects.annotate(
            full_name=Concat('first_name', Value(' '), 'last_name', output_field=CharField())
        ).filter(
            Q(username__iexact=input_value) |
            Q(email__iexact=input_value) |
            Q(first_name__iexact=input_value) |
            Q(last_name__iexact=input_value) |
            Q(full_name__iexact=input_value)
        ).first()

        if not user:
            roll_query = input_value.split('@')[0] if '@' in input_value else input_value
            student = Student.objects.filter(roll_number__iexact=roll_query).first()
            if student:
                profile = _get_profile_for_student(student)
                user = profile.user if profile and getattr(profile, 'user', None) else None
                if not user:
                    username_safe = student.roll_number.lower()
                    user, created = User.objects.get_or_create(username=username_safe, defaults={
                        'email': f"{username_safe}@college.edu",
                        'is_active': True,
                    })
                    if created:
                        user.set_password(username_safe)
                        user.save()
                    try:
                        up, _ = UserProfile.objects.get_or_create(user=user)
                        up.student = student
                        up.role = getattr(UserProfile.Role, 'STUDENT', up.role)
                        up.college_email = user.email
                        up.save()
                    except Exception:
                        pass

        if user:
            request.session['reset_user_id'] = user.id
            return redirect('students:password_reset_confirm')
        else:
            messages.error(request, "No account found with that Admin Full Name, Email, or Roll Number.")
    return render(request, 'students/password_reset_request.html')


def password_reset_confirm(request):
    user_id = request.session.get('reset_user_id')
    if not user_id:
        return render(request, 'students/password_reset_confirm.html', {'validlink': False})

    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        if not password or not confirm_password:
            messages.error(request, "Please enter and confirm your new password.")
            return render(request, 'students/password_reset_confirm.html', {'validlink': True})

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, 'students/password_reset_confirm.html', {'validlink': True})

        if len(password) < 6:
            messages.error(request, "Password must be at least 6 characters long.")
            return render(request, 'students/password_reset_confirm.html', {'validlink': True})

        fresh_user = User.objects.get(pk=user.pk)
        fresh_user.set_password(password)
        fresh_user.is_active = True
        fresh_user.save(update_fields=['password', 'is_active'])

        request.session.pop('reset_user_id', None)
        messages.success(request, "Password updated successfully! You can now log in.")
        return redirect('students:login')

    return render(request, 'students/password_reset_confirm.html', {'validlink': True})


def custom_logout(request):
    logout(request)
    return redirect('students:login')


# =========================================================
# DASHBOARD VIEWS & ACHIEVEMENTS MANAGEMENT
# =========================================================

@login_required(login_url='students:login')
def student_dashboard(request):
    if _user_is_teacher(request.user) and not _is_student_role(request.user):
        return redirect('students:analytics_dashboard')

    user_identifier = request.user.username.split('@')[0]
    student = Student.objects.filter(
        Q(roll_number__iexact=request.user.username) |
        Q(roll_number__iexact=user_identifier)
    ).first()

    achievements = list(student.achievements.all()) if student else []

    scatter_data = []
    scatter_quadrants = {
        'top_right': [],
        'top_left': [],
        'bottom_right': [],
        'bottom_left': [],
    }

    context = {
        'student': student,
        'user_display_name': get_user_display_name(request.user),
        'achievements': achievements,
        'overall_academic_avg': 0.0,
        'overall_att': 0.0,
        'total_subjects_evaluated': 0,
        'subject_performances': [],
        'subject_attendances': [],
        'scatter_data': scatter_data,
        'scatter_quadrants': scatter_quadrants,
        'quadrants': scatter_quadrants,
        'quadrant_top_right': scatter_quadrants.get('top_right', []),
        'quadrant_top_left': scatter_quadrants.get('top_left', []),
        'quadrant_bottom_right': scatter_quadrants.get('bottom_right', []),
        'quadrant_bottom_left': scatter_quadrants.get('bottom_left', []),
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
            m.strongest_unit = ai_analysis.get('strongest_unit', 'N/A')
            m.weakest_unit = ai_analysis.get('weakest_unit', 'N/A')

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
            'achievements': achievements,
        })

    return render(request, 'student_dashboard.html', context)


@login_required
def add_achievement(request, student_id=None):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        category = request.POST.get('category', 'ACADEMIC')
        date_awarded = request.POST.get('date_awarded')

        if student_id:
            student = get_object_or_404(Student, id=student_id)
        else:
            profile = _get_profile(request.user)
            student = getattr(profile, 'student', None) if profile else None

        if student and title:
            Achievement.objects.create(
                student=student,
                title=title,
                description=description,
                category=category,
                date_achieved=date_awarded if date_awarded else None
            )
            messages.success(request, "Achievement added successfully!")

    return redirect(request.META.get('HTTP_REFERER', 'students:student_dashboard'))


# =========================================================
# ANALYTICS DASHBOARD & VISUAL SCATTER QUADRANTS
# =========================================================

@login_required
def analytics_dashboard(request):
    if _is_student_role(request.user) and not _user_is_teacher(request.user):
        messages.warning(request, "Access restricted. You have been redirected to your student portal.")
        return redirect('students:student_dashboard')

    if request.method == 'POST' and request.FILES.get('excel_file'):
        uploaded_file = request.FILES['excel_file']

        try:
            excel_batch = ExcelBatch.objects.create(
                filename=uploaded_file.name,
                academic_year=request.POST.get('year', 'General'),
                uploaded_by=request.user if request.user.is_authenticated else None
            )

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

                        student_obj, created = Student.objects.get_or_create(
                            roll_number=roll,
                            defaults={'name': f"Student {roll}", 'created_in_batch': excel_batch}
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
                                'excel_batch': excel_batch
                            }
                        )
                        records_created += 1

                excel_batch.record_count = records_created
                excel_batch.save()

                messages.success(request, f"Streamlined attendance uploaded for {records_created} records!")
                return redirect('/dashboard/')

            df, missing_cols = map_dataframe_columns(df)
            if missing_cols:
                messages.error(
                    request,
                    f"Upload Failed! Missing required columns in file: {', '.join(missing_cols)}"
                )
                excel_batch.delete()
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
                        defaults={'name': name, 'created_in_batch': excel_batch}
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
                            'excel_batch': excel_batch
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
                                'excel_batch': excel_batch
                            }
                        )

                    records_created += 1

            excel_batch.record_count = records_created
            excel_batch.save()
            messages.success(request, f"Success! Imported/Updated {records_created} student records.")
            return redirect('/dashboard/')

        except Exception as e:
            messages.error(request, f"Error processing file: {str(e)}")
            try:
                if 'excel_batch' in locals():
                    excel_batch.delete()
            except Exception:
                pass
            return redirect('/dashboard/')

    selected_student_id = request.GET.get('student_id') or request.GET.get('dossier')
    search_query = request.GET.get('search', '').strip()
    selected_subject_id = request.GET.get('subject')
    selected_year = request.GET.get('year')

    subjects = Subject.objects.all()

    uploaded_files_qs = ExcelBatch.objects.all()

    context = {
        'subjects': subjects,
        'user_display_name': get_user_display_name(request.user),
        'selected_subject_id': selected_subject_id,
        'selected_year': selected_year,
        'years': YEAR_CHOICES,
        'search_query': search_query,
        'is_student_mode': False,
        'uploaded_files': uploaded_files_qs,
        'excel_batches': uploaded_files_qs,
        'achievements': [],
        'has_achievements': False,
    }

    if selected_student_id or search_query:
        student = None
        if selected_student_id:
            student = Student.objects.filter(Q(id__iexact=selected_student_id) | Q(roll_number__iexact=selected_student_id)).first()
        elif search_query:
            student = Student.objects.filter(
                Q(roll_number__iexact=search_query) | Q(name__icontains=search_query)
            ).first()

        if not student and search_query:
            messages.error(request, f"No student found with Roll Number or Name matching '{search_query}'.")

        if student:
            context['is_student_mode'] = True
            context['student'] = student
            context['student_display_name'] = student.name.title() if student.name else student.name

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

                ai_analysis = analyze_student_performance(m, overall_att)
                m.strongest_unit = ai_analysis.get('strongest_unit', 'N/A')
                m.weakest_unit = ai_analysis.get('weakest_unit', 'N/A')

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
            achievements = list(student.achievements.all())

            context.update({
                'achievements': achievements,
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
                'has_achievements': len(achievements) > 0,
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

    u1_percs = []
    u2_percs = []
    u3_percs = []
    u4_percs = []

    marks_list = list(all_marks_qs)

    for m in marks_list:
        subj = getattr(m, 'subject', None)
        if not subj:
            continue

        u1_max = getattr(subj, 'unit_1_max', None) or getattr(subj, 'max_unit_1', None) or 0
        u2_max = getattr(subj, 'unit_2_max', None) or getattr(subj, 'max_unit_2', None) or 0
        u3_max = getattr(subj, 'unit_3_max', None) or getattr(subj, 'max_unit_3', None) or 0
        u4_max = getattr(subj, 'unit_4_max', None) or getattr(subj, 'max_unit_4', None) or 0

        try:
            if getattr(m, 'unit_1_marks', None) is not None and u1_max and float(u1_max) > 0:
                u1_percs.append((float(m.unit_1_marks) / float(u1_max)) * 100.0)
        except Exception:
            logger.exception("unit 1 percent calc failed for mark id %s", getattr(m, 'id', None))

        try:
            if getattr(m, 'unit_2_marks', None) is not None and u2_max and float(u2_max) > 0:
                u2_percs.append((float(m.unit_2_marks) / float(u2_max)) * 100.0)
        except Exception:
            logger.exception("unit 2 percent calc failed for mark id %s", getattr(m, 'id', None))

        try:
            if getattr(m, 'unit_3_marks', None) is not None and u3_max and float(u3_max) > 0:
                u3_percs.append((float(m.unit_3_marks) / float(u3_max)) * 100.0)
        except Exception:
            logger.exception("unit 3 percent calc failed for mark id %s", getattr(m, 'id', None))

        try:
            if getattr(m, 'unit_4_marks', None) is not None and u4_max and float(u4_max) > 0:
                u4_percs.append((float(m.unit_4_marks) / float(u4_max)) * 100.0)
        except Exception:
            logger.exception("unit 4 percent calc failed for mark id %s", getattr(m, 'id', None))

    u1_avg = round(sum(u1_percs) / len(u1_percs), 1) if u1_percs else 0.0
    u2_avg = round(sum(u2_percs) / len(u2_percs), 1) if u2_percs else 0.0
    u3_avg = round(sum(u3_percs) / len(u3_percs), 1) if u3_percs else 0.0
    u4_avg = round(sum(u4_percs) / len(u4_percs), 1) if u4_percs else 0.0

    unit_mastery = [u1_avg, u2_avg, u3_avg, u4_avg]

    total_st = Student.objects.filter(year=selected_year).count() if selected_year else Student.objects.count()
    eval_count = len(marks_list)

    passed_evals = sum(1 for m in marks_list if getattr(m, 'result_status', None) == 'PASS')
    pass_rate = round((passed_evals / eval_count * 100), 1) if eval_count else 0.0

    valid_percentages = [
        float(m.percentage) for m in marks_list 
        if getattr(m, 'percentage', None) is not None
    ]
    overall_avg = round(sum(valid_percentages) / len(valid_percentages), 1) if valid_percentages else 0.0

    all_students_list = Student.objects.filter(year=selected_year) if selected_year else Student.objects.all()

    att_scores = [calculate_overall_attendance(st) for st in all_students_list]
    att_avg = round(sum(att_scores) / len(att_scores), 1) if att_scores else 0.0
    att_map = {st.id: calculate_overall_attendance(st) for st in all_students_list}

    student_marks_map = {}
    for mark in marks_list:
        student_marks_map.setdefault(mark.student_id, []).append(mark)
    
    master_student_roster = []

    quadrant_top_right = []
    quadrant_top_left = []
    quadrant_bottom_right = []
    quadrant_bottom_left = []

    for st in all_students_list:
        st_m = student_marks_map.get(st.id, [])
        att_val = att_map.get(st.id, 0.0)
        st_avg = round(sum(m.percentage for m in st_m) / len(st_m), 1) if st_m else getattr(st, 'academic_avg', 0.0)

        first_m = st_m[0] if st_m else None
        ai_data = analyze_student_performance(first_m, att_val) if first_m else {
            'fail_prob': 0, 'risk_level': 'STABLE', 'badge_class': 'success', 'remedial_plan': 'Maintain current study routine.', 'remedial_str': 'Maintain current study routine.'
        }

        action_status = compute_smart_action_status(att_val, st_avg)

        color = "#28a745" if (att_val >= 75 and st_avg >= 50) else "#ffc107" if (att_val < 75 and st_avg >= 50) else "#fd7e14" if (att_val >= 75 and st_avg < 50) else "#dc3545"
        quadrant = "Stars" if (att_val >= 75 and st_avg >= 50) else "Potential" if (att_val < 75 and st_avg >= 50) else "High Effort" if (att_val >= 75 and st_avg < 50) else "Critical"

        st_point = {
            'x': att_val,
            'y': st_avg,
            'name': st.name,
            'roll': st.roll_number,
            'color': color,
            'quadrant': quadrant
        }

        if att_val >= 75.0 and st_avg >= 50.0:
            quadrant_top_right.append(st_point)
        elif att_val < 75.0 and st_avg >= 50.0:
            quadrant_top_left.append(st_point)
        elif att_val >= 75.0 and st_avg < 50.0:
            quadrant_bottom_right.append(st_point)
        else:
            quadrant_bottom_left.append(st_point)

        master_student_roster.append({
            'student': st,
            'roll_number': st.roll_number,
            'name': st.name.title() if st.name else st.name,
            'class_label': st.get_year_display(),
            'avg_marks': st_avg,
            'attendance': att_val,
            'action_status': action_status,
            'risk': ai_data['fail_prob'],
            'level': ai_data['risk_level'],
            'badge': ai_data['badge_class'],
            'remedial': ai_data['remedial_str']
        })

    sort_mode = request.GET.get('sort', 'roll')

    for item in master_student_roster:
        st = item.get('student')
        st_marks = student_marks_map.get(st.id, []) if st else []
        total_marks = 0.0
        total_max = 0.0

        for m in st_marks:
            components = [
                'unit_1_marks', 'unit_2_marks', 'unit_3_marks', 'unit_4_marks',
                'internal_marks', 'practical_marks', 'assignment_marks', 'presentation_marks'
            ]
            m_total = 0.0
            for comp in components:
                val = getattr(m, comp, None)
                if val is not None:
                    try:
                        m_total += float(val)
                    except Exception:
                        pass
            total_marks += m_total

            subj = getattr(m, 'subject', None)
            subj_max = 0.0
            if subj:
                subj_max = float(getattr(subj, 'total_max_marks', 0) or 0)
                if not subj_max:
                    subj_max += float(getattr(subj, 'unit_1_max', 0) or 0)
                    subj_max += float(getattr(subj, 'unit_2_max', 0) or 0)
                    subj_max += float(getattr(subj, 'unit_3_max', 0) or 0)
                    subj_max += float(getattr(subj, 'unit_4_max', 0) or 0)
                    subj_max += float(getattr(subj, 'max_internal_marks', 0) or 0)
                    subj_max += float(getattr(subj, 'max_practical_marks', 0) or 0)
                    subj_max += float(getattr(subj, 'max_assignment_marks', 0) or 0)
                    subj_max += float(getattr(subj, 'max_presentation_marks', 0) or 0)
            total_max += subj_max

        if total_max and total_max > 0:
            percentage = round((total_marks / total_max) * 100, 1)
        else:
            percentage = round(item.get('avg_marks', 0), 1) if item.get('avg_marks') is not None else None

        status = item.get('status') or calculate_result_status(percentage)
        grade = 'F' if status == 'FAIL' else calculate_grade(percentage)

        item['total_marks'] = int(total_marks) if total_marks is not None else None
        item['total_max'] = int(total_max) if total_max is not None and total_max > 0 else None
        item['percentage'] = percentage
        item['grade'] = grade
        item['status'] = status

    if sort_mode == 'rank':
        master_student_roster.sort(key=lambda x: (x.get('percentage') is None, -(x.get('percentage') or x.get('avg_marks', 0))))
        current_rank = 0
        prev_score = None
        for idx, it in enumerate(master_student_roster, start=1):
            score = it.get('percentage') if it.get('percentage') is not None else it.get('avg_marks', 0)
            if prev_score is None or score != prev_score:
                current_rank = idx
                prev_score = score
            it['rank'] = current_rank
    else:
        try:
            master_student_roster.sort(key=lambda x: (str(x.get('roll_number') or '').lower()))
        except Exception:
            pass
        for it in master_student_roster:
            it.pop('rank', None)

    department_toppers = sorted(master_student_roster, key=lambda x: (x.get('percentage') is None, -(x.get('percentage') or x.get('avg_marks', 0))))[:5]
    bottom_remedial_roster = sorted(master_student_roster, key=lambda x: (-(x.get('risk', 0) or 0)))[:5]

    scatter_data = [
        {
            'x': item['attendance'],
            'y': item['avg_marks'],
            'name': item['student'].name,
            'color': "#28a745" if (item['attendance'] >= 75 and item['avg_marks'] >= 50) else "#ffc107" if (item['attendance'] < 75 and item['avg_marks'] >= 50) else "#fd7e14" if (item['attendance'] >= 75 and item['avg_marks'] < 50) else "#dc3545"
        } for item in master_student_roster
    ]

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
        'scatter_quadrants': {
            'top_right': quadrant_top_right,
            'top_left': quadrant_top_left,
            'bottom_right': quadrant_bottom_right,
            'bottom_left': quadrant_bottom_left,
        },
        'quadrant_top_right': quadrant_top_right,
        'quadrant_top_left': quadrant_top_left,
        'quadrant_bottom_right': quadrant_bottom_right,
        'quadrant_bottom_left': quadrant_bottom_left,
        'ai_copilot_recommendation': (
            f"Department Executive Summary: Enrollment of {total_st} students. "
            f"Academic Score: {overall_avg}% | Attendance: {att_avg}%. "
            f"Unit Mastery Averages: U1 ({unit_mastery[0]}%), U2 ({unit_mastery[1]}%), U3 ({unit_mastery[2]}%), U4 ({unit_mastery[3]}%)."
        ),
        'sort_mode': sort_mode,
    })

    return render(request, 'students/dashboard.html', context)


# =========================================================
# MULTI-SHEET EXCEL BULK INGESTION & DATA MANAGEMENT VIEWS
# =========================================================

@login_required
def upload_excel_view(request):
    if _is_student_role(request.user):
        messages.error(request, "Access denied. Students cannot upload sheets.")
        return redirect('students:student_dashboard')

    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']
        file_name = excel_file.name

        try:
            xls = pd.ExcelFile(excel_file)
            sheet_names = xls.sheet_names

            if len(sheet_names) < 3:
                messages.error(request, "Uploaded file must contain at least 3 sheets/tabs.")
                return redirect('students:upload_excel')

            with transaction.atomic():
                excel_batch = ExcelBatch.objects.create(
                    filename=file_name,
                    uploaded_by=request.user if request.user.is_authenticated else None
                )

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

                    student, created = Student.objects.get_or_create(
                        roll_number=roll,
                        defaults={'name': student_name or roll, 'created_in_batch': excel_batch}
                    )
                    if not created and student.name != student_name and student_name:
                        student.name = student_name
                        student.save()

                    subject = subject_lookup.get(subj_name)
                    if not subject:
                        subject = Subject.objects.create(name=subj_name)
                        subject_lookup[subj_name] = subject

                    def get_validated_mark(col, max_val):
                        val = row.get(col)
                        if pd.notna(val) and str(val).strip() != '':
                            try:
                                num = float(val)
                                # Cap excess scores automatically instead of raising an error
                                if max_val > 0 and num > max_val:
                                    return float(max_val)
                                return num
                            except ValueError:
                                return None
                        return None

                    u1_m = getattr(subject, 'unit_1_max', 0) or getattr(subject, 'max_unit_1', 0) or 0
                    u2_m = getattr(subject, 'unit_2_max', 0) or getattr(subject, 'max_unit_2', 0) or 0
                    u3_m = getattr(subject, 'unit_3_max', 0) or getattr(subject, 'max_unit_3', 0) or 0
                    u4_m = getattr(subject, 'unit_4_max', 0) or getattr(subject, 'max_unit_4', 0) or 0
                    pr_m = getattr(subject, 'max_practical_marks', 0) or 0
                    int_m = getattr(subject, 'max_internal_marks', 0) or 0
                    ass_m = getattr(subject, 'max_assignment_marks', 0) or 0
                    pres_m = getattr(subject, 'max_presentation_marks', 0) or 0

                    semester = int(row.get('Semester', 1)) if pd.notna(row.get('Semester')) else 1

                    marks_obj, _ = Marks.objects.get_or_create(
                        student=student,
                        subject=subject,
                        semester=semester
                    )

                    marks_obj.unit_1_marks = get_validated_mark('Unit 1', u1_m)
                    marks_obj.unit_2_marks = get_validated_mark('Unit 2', u2_m)
                    marks_obj.unit_3_marks = get_validated_mark('Unit 3', u3_m)
                    marks_obj.unit_4_marks = get_validated_mark('Unit 4', u4_m)

                    marks_obj.practical_marks = get_validated_mark('Practical', pr_m)
                    marks_obj.internal_marks = get_validated_mark('Internal', int_m)
                    marks_obj.assignment_marks = get_validated_mark('Assignment', ass_m)
                    marks_obj.presentation_marks = get_validated_mark('Presentation', pres_m)

                    marks_obj.excel_batch = excel_batch
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
                            defaults={'name': str(row.get('Name', roll)).strip(), 'created_in_batch': excel_batch}
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
                            'excel_batch': excel_batch
                        }
                    )

            messages.success(request, f"Success! Excel batch '{file_name}' imported seamlessly.")
            return redirect('students:analytics_dashboard')

        except Exception as e:
            try:
                if 'excel_batch' in locals():
                    excel_batch.delete()
            except Exception:
                pass
            messages.error(request, f"Import error: {str(e)}")

    return render(request, 'students/upload_excel.html')


@login_required
def upload_history(request):
    if _is_student_role(request.user):
        messages.error(request, "Access denied.")
        return redirect('students:student_dashboard')

    year_summaries = []
    for year_code, year_label in YEAR_CHOICES:
        count = Student.objects.filter(year=year_code).count()
        year_summaries.append({
            'code': year_code,
            'label': year_label,
            'student_count': count
        })

    excel_batches = ExcelBatch.objects.all().order_by('-uploaded_at')

    return render(request, 'students/upload_history.html', {
        'year_summaries': year_summaries,
        'excel_batches': excel_batches,
    })


@login_required
def delete_year_data(request, year_code):
    if _is_student_role(request.user):
        messages.error(request, "Access denied.")
        return redirect('students:student_dashboard')

    if request.method == 'POST':
        students_to_delete = Student.objects.filter(year=year_code)
        count = students_to_delete.count()

        with transaction.atomic():
            students_to_delete.delete()

        messages.success(request, f"Successfully purged all data for Year '{year_code}' ({count} students removed).")

    return redirect('students:upload_history')


@login_required
def delete_excel_batch(request, batch_id):
    if _is_student_role(request.user):
        messages.error(request, "Access denied.")
        return redirect('students:student_dashboard')

    if request.method == 'POST':
        batch = get_object_or_404(ExcelBatch, id=batch_id)
        filename = batch.filename

        try:
            batch.delete_associated_records()
            messages.success(request, f"Excel workbook batch '{filename}' successfully deleted.")
        except Exception as e:
            messages.error(request, f"Failed to delete batch '{filename}': {str(e)}")

    return redirect('students:upload_history')