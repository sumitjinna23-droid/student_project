"""
URL configuration for student_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
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
    
    # Include all routes from the 'students' app
    path('', include('students.urls')),
]

# Serve media files (uploaded Excel sheets, etc.) locally in debug mode
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)