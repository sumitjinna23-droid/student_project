"""
URL configuration for student_project project.
"""

from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static
from django.utils.html import format_html

# Customize Admin Panel Header & Branding
admin.site.site_title = "Academic Portal"
admin.site.index_title = "Welcome to Department Management"
admin.site.site_header = format_html(
    'Academic Admin | <a href="/dashboard/" style="color: #ffc107; text-decoration: none; font-weight: bold; margin-left: 10px;">📊 Go to Analytics Dashboard</a>'
)

urlpatterns = [
    # Redirect root domain (http://127.0.0.1:8000/) directly to the analytics dashboard
    path('', lambda request: redirect('students:analytics_dashboard')),

    # Django Admin Panel
    path('admin/', admin.site.urls),

    # FIX: removed `path('accounts/', include('django.contrib.auth.urls'))`.
    #
    # This was wiring up a SECOND, completely independent password-reset
    # and login system alongside your custom one:
    #   - Django's built-in PasswordResetView lives at /accounts/password_reset/
    #   - Your custom one lives at /password-reset/ (students/urls.py)
    # Both existed at the same time. The built-in one:
    #   - has NO support for resetting by Roll Number or Admin Full Name —
    #     it only accepts a real, deliverable email address, so it directly
    #     conflicts with requirements #2/#3
    #   - requires a working EMAIL_BACKEND (SMTP or similar) to actually
    #     send the reset link — if that isn't configured (common in local
    #     dev, where EMAIL_BACKEND often defaults to the console backend or
    #     is unset), anyone who ends up on THIS flow instead of yours would
    #     see it silently "succeed" with no usable email ever arriving
    #   - also included its own /accounts/login/ and /accounts/logout/,
    #     duplicating your custom /login/ and /logout/ with different
    #     behavior (default ModelBackend-only, no roll-number/teacher-email
    #     handling)
    #
    # Since students/urls.py already fully replaces login, logout, and
    # password reset with your custom multi-identifier flow, this include
    # was pure redundancy with a real risk of users (or a stray link
    # somewhere) landing on the broken duplicate instead of yours.
    #
    # If you specifically want Django's built-in reset-by-email as an
    # ADDITIONAL fallback for admins with real, deliverable email addresses,
    # it needs to be re-added deliberately with EMAIL_BACKEND configured —
    # not left as an unused parallel system.

    # Include all routes from the 'students' app
    path('', include('students.urls')),
]

# Serve media files (uploaded Excel sheets, etc.) locally in debug mode
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)