from django.urls import path
from . import views

urlpatterns = [
    # Authentication
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboards
    path('', views.dashboard, name='dashboard'),
    path('manager-dashboard/', views.manager_dashboard, name='manager_dashboard'),
    path('agent-dashboard/', views.agent_dashboard, name='agent_dashboard'),

    # User Management (Managers only)
    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.create_user, name='create_user'),
    path('users/<int:user_id>/update/', views.update_user, name='update_user'),
    path('users/<int:user_id>/toggle-status/', views.toggle_user_status, name='toggle_user_status'),

    # Profile
    path('profile/', views.profile, name='profile'),

    path('setup-password/<uidb64>/<token>/', views.setup_password, name='setup_password'),
path('users/<int:user_id>/delete/', views.delete_user, name='delete_user'),
]
