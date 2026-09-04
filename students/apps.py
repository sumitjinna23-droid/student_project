# students/apps.py
import logging
from django.apps import AppConfig

logger = logging.getLogger(__name__)


class StudentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'students'

    def ready(self):
        # FIX: this used to be
        #     try:
        #         import students.signals
        #     except Exception:
        #         pass
        # which is exactly why signals.py's broken `from .models import
        # Teacher` (should have been AllowedTeacher) went unnoticed —
        # the ImportError was caught and silently discarded, so the signal
        # was never registered and nothing ever indicated a problem.
        # Now it logs loudly instead of hiding the failure. If signals.py
        # is broken again in the future, this will show up in your logs
        # immediately instead of manifesting as a mysterious missing
        # behavior weeks later.
        try:
            import students.signals  # noqa: F401
        except Exception:
            logger.exception(
                "Failed to import students.signals — signal handlers "
                "(student account provisioning, teacher-deletion cleanup) "
                "are NOT registered. Fix the import error above."
            )