"""
URL configuration for students app (App Level).
"""
from django.urls import path
from . import views

app_name = 'students'

urlpatterns = [
    # Auth URLs
    path('login/', views.custom_login, name='login'),
    path('logout/', views.custom_logout, name='logout'),
    path('first-time-setup/', views.first_time_setup, name='first_time_setup'),
    
    # Dashboards & Views
    path('dashboard/', views.analytics_dashboard, name='analytics_dashboard'),
    path('student-dashboard/', views.student_dashboard, name='student_dashboard'),
    path('upload-excel/', views.upload_excel_view, name='upload_excel'),
]