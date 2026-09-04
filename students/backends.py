# students/backends.py
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.db.models import Q

from .models import Student, AllowedTeacher, UserProfile

class UnifiedDatabaseBackend(ModelBackend):
    """
    Authenticate only if there is an active DB record:
      - Student (lookup by roll number)
      - AllowedTeacher (lookup by email)
      - Admin/teacher user (username or email) if they are staff/superuser or linked to AllowedTeacher/Student
    Newly created Student records are expected to have a linked User (see the
    post_save signal in signals.py). If no linked User exists we won't
    authenticate (strict). When a Student is deleted the linked User will be
    deactivated (see signals.py).

    ROOT CAUSE OF "students can't log in even after resetting their
    password" (found here): every non-staff, non-superuser lookup in this
    file used `getattr(user, 'userprofile', None)` to find the user's
    UserProfile. But UserProfile.user's related_name in models.py is
    `'profile'`, not `'userprofile'` — so that getattr ALWAYS returned
    None, the AllowedTeacher-email fallback also always failed for
    students (a student's account email isn't a teacher email), and this
    backend returned None for EVERY student login attempt, unconditionally,
    regardless of whether the password was correct. If this backend is the
    only one listed in AUTHENTICATION_BACKENDS (no default ModelBackend
    alongside it), this alone fully explains total student lockout.

    Similarly, the roll-number branch used
    `getattr(student, 'userprofile', None) or getattr(student, 'profile', None)`
    to go from a Student to its UserProfile — but the correct reverse
    accessor there is `student.user_account` (UserProfile.student's
    related_name). Fixed below.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = (username or '').strip()
        if not identifier or password is None:
            return None

        # 1) If an exact username exists (admin or teacher user)
        user = User.objects.filter(username__iexact=identifier).first()
        if user:
            if not user.is_active:
                return None
            # superuser/staff: allow if password matches
            if user.is_superuser or user.is_staff:
                return user if user.check_password(password) else None
            # otherwise, allow only if linked to an active Student or AllowedTeacher
            # FIX: 'profile', not 'userprofile' — see class docstring.
            profile = getattr(user, 'profile', None)
            if profile and getattr(profile, 'student', None):
                # ensure student still exists and is active (if model has is_active)
                stud = profile.student
                if stud and (not hasattr(stud, 'is_active') or stud.is_active):
                    return user if user.check_password(password) else None
            # allow if email belongs to an AllowedTeacher
            if user.email and AllowedTeacher.objects.filter(email__iexact=user.email).exists():
                return user if user.check_password(password) else None
            return None

        # 2) If an email-like identifier provided, try teacher email or user email
        if '@' in identifier:
            # teacher email (AllowedTeacher)
            teacher = AllowedTeacher.objects.filter(email__iexact=identifier).first()
            if teacher:
                # teacher must have a linked Django User with same email and active
                linked_user = User.objects.filter(email__iexact=identifier, is_active=True).first()
                if linked_user and linked_user.check_password(password):
                    return linked_user
                return None

            # user by email (could be admin)
            user_by_email = User.objects.filter(email__iexact=identifier).first()
            if user_by_email and user_by_email.is_active:
                if user_by_email.is_superuser or user_by_email.is_staff:
                    return user_by_email if user_by_email.check_password(password) else None
                # FIX: 'profile', not 'userprofile' — see class docstring.
                profile = getattr(user_by_email, 'profile', None)
                if profile and getattr(profile, 'student', None):
                    stud = profile.student
                    if stud and (not hasattr(stud, 'is_active') or stud.is_active):
                        return user_by_email if user_by_email.check_password(password) else None
            return None

        # 3) Otherwise treat as roll number (strip domain if someone typed roll@domain)
        roll = identifier.split('@')[0]
        student = Student.objects.filter(roll_number__iexact=roll).first()
        if student:
            # ensure student is active (if model has is_active) and hasn't been deleted
            if hasattr(student, 'is_active') and not student.is_active:
                return None

            # FIX: the correct reverse accessor from Student to UserProfile
            # is `user_account` (UserProfile.student's related_name), not
            # `userprofile` or `profile` — those don't exist on Student.
            profile = getattr(student, 'user_account', None)
            user = None
            if profile and getattr(profile, 'user', None):
                user = profile.user

            # If no linked user: we do NOT create here (creation happens on
            # Student post_save — see signals.py).
            if not user:
                return None

            if not user.is_active:
                return None

            return user if user.check_password(password) else None

        # no match found -> deny
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None