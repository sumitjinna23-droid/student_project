# students/signals.py
import logging
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.db import transaction

# FIX: this was `from .models import Teacher`, but there is no `Teacher`
# model anywhere in models.py — the actual model is `AllowedTeacher`. That
# import error meant this whole file threw an exception the moment
# apps.py tried to import it. Because apps.py's ready() wrapped that import
# in a bare `except Exception: pass`, the failure was completely silent —
# this signal has never actually been registered or run, ever, since this
# file was written. See the apps.py fix for the other half of this.
from .models import AllowedTeacher, Student, UserProfile

User = get_user_model()
logger = logging.getLogger(__name__)


@receiver(post_delete, sender=AllowedTeacher)
def delete_user_by_email_when_teacher_deleted(sender, instance, **kwargs):
    """
    When an AllowedTeacher row is deleted, remove the Django user with the
    same email (case-insensitive). Do not delete if that user is
    staff/superuser; instead deactivate.
    """
    try:
        email = getattr(instance, 'email', None)
        if not email:
            return
        with transaction.atomic():
            user_qs = User.objects.filter(email__iexact=email)
            for u in user_qs:
                if u.is_superuser or u.is_staff:
                    u.is_active = False
                    u.save(update_fields=['is_active'])
                else:
                    u.delete()
    except Exception:
        # FIX: was a bare `except Exception: pass` — logging now instead of
        # swallowing silently, so a failure here is at least discoverable.
        logger.exception(
            "delete_user_by_email_when_teacher_deleted failed for email=%s",
            getattr(instance, 'email', '<unknown>')
        )


# =========================================================
# Moved from models.py: Student account auto-provisioning.
# Consolidating all signal receivers into this one file (rather than having
# some in models.py and some here) so there's a single place to look for
# "what runs when a Student is created/deleted" — models.py now just
# defines the model classes.
# =========================================================

@receiver(post_save, sender=Student)
def ensure_user_for_student(sender, instance, created, **kwargs):
    """
    When a new Student is created, ensure there is a linked Django User so
    the student can log in. Temporary password = their (normalized,
    uppercase) roll_number, matched by a lowercased username — students are
    expected to change this via first_time_setup / password reset.

    Only runs on creation (`created` guard) — NOT on every save — so
    routine updates (e.g. re-importing the same students from a new Excel
    batch) don't keep re-touching every existing student's account.
    Wrapped in transaction.atomic() so a partial failure can't leave a User
    committed with no profile/role attached.
    """
    if not created:
        return

    try:
        with transaction.atomic():
            username_safe = instance.roll_number.lower()
            user, u_created = User.objects.get_or_create(
                username=username_safe,
                defaults={
                    'email': f"{username_safe}@college.local",
                    'is_active': True,
                }
            )
            if u_created:
                user.set_password(username_safe)
                user.save()

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.student = instance
            profile.role = UserProfile.Role.STUDENT
            profile.roll_number = username_safe
            profile.save()
    except Exception:
        logger.exception(
            "ensure_user_for_student failed for roll_number=%s",
            getattr(instance, 'roll_number', '<unknown>')
        )


@receiver(post_delete, sender=Student)
def deactivate_user_on_student_delete(sender, instance, **kwargs):
    """
    When a Student is deleted, deactivate the linked Django User.

    Uses `instance.user_account` — the correct reverse accessor
    (UserProfile.student's related_name) — not `userprofile`/`profile`,
    which don't exist on Student.
    """
    try:
        profile = getattr(instance, 'user_account', None)
        if profile is None:
            return
        user = getattr(profile, 'user', None)
        if user:
            user.is_active = False
            user.save(update_fields=['is_active'])
    except Exception:
        logger.exception(
            "deactivate_user_on_student_delete failed for student id=%s",
            getattr(instance, 'id', '<unknown>')
        )