"""
URL configuration for students app (App Level).
"""
from django.urls import path
from . import views

app_name = 'students'

urlpatterns = [
    # Auth & Setup URLs
    path('login/', views.custom_login, name='login'),
    path('logout/', views.custom_logout, name='logout'),
    path('first-time-setup/', views.first_time_setup, name='first_time_setup'),
    
    # REQ 1: Password Reset Routes
    path('password-reset/', views.password_reset_request, name='password_reset_request'),
    path('password-reset/confirm/', views.password_reset_confirm, name='password_reset_confirm'),
    
    # Dashboards & Views
    path('dashboard/', views.analytics_dashboard, name='analytics_dashboard'),
    path('student-dashboard/', views.student_dashboard, name='student_dashboard'),
    
    # REQ 2: Achievement Management Route
    path('achievements/add/', views.add_achievement, name='add_achievement'),
    path('achievements/add/<int:student_id>/', views.add_achievement, name='add_achievement_for_student'),
    
    # REQ 4: Multi-sheet Upload, History & Year Purge Routes
    path('upload-excel/', views.upload_excel_view, name='upload_excel'),
    path('upload-history/', views.upload_history, name='upload_history'),
    path('delete-year-data/<str:year_code>/', views.delete_year_data, name='delete_year_data'),

    # Deletion routes for Excel batches (two route patterns / alias names provided so templates/legacy links work)
    path('upload-history/delete-batch/<int:batch_id>/', views.delete_excel_batch, name='delete_excel_batch'),
    path('delete-batch/<int:batch_id>/', views.delete_excel_batch, name='delete_batch'),
]