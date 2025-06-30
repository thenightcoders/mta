from django.urls import path
from . import views

urlpatterns = [
    # Transfer management
    path('', views.transfer_list, name='transfer_list'),
    path('create/', views.create_transfer, name='create_transfer'),
    path('<int:transfer_id>/', views.transfer_detail, name='transfer_detail'),
    path('<int:transfer_id>/validate/', views.validate_transfer, name='validate_transfer'),
    path('<int:transfer_id>/execute/', views.execute_transfer, name='execute_transfer'),
    path('pending/', views.pending_transfers, name='pending_transfers'),

    # Commission configuration
    path('commissions/', views.commission_config_list, name='commission_config_list'),
    path('commissions/create/', views.create_commission_config, name='create_commission_config'),
    path('commissions/<int:config_id>/toggle/', views.toggle_commission_config, name='toggle_commission_config'),
    path('commissions/<int:config_id>/update/', views.update_commission_config, name='update_commission_config'),

    # earnings
    path('commissions/overview/', views.commissions_overview, name='commissions_overview'),
    # path('commission/<int:commission_id>/detail/', views.commission_detail, name='commission_detail')
    path('commissions/clear/', views.clear_commissions, name='clear_commissions'),

]
