"""
URL configuration for students app (App Level).
"""
from django.urls import path
from . import views

app_name = 'students'

urlpatterns = [
    # Dashboard route: handles analytics overview and single-student dossier view
    path('dashboard/', views.analytics_dashboard, name='analytics_dashboard'),
    
    # Route for uploading the 3-sheet Excel workbook
    path('upload-excel/', views.upload_excel_view, name='upload_excel'),
]