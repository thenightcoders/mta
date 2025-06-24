from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Transfer, CommissionConfig, CommissionDistribution, TRANSFER_STATUS
from .forms import TransferForm, TransferValidationForm, CommissionConfigForm
from users.models import log_user_activity
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth, TruncYear
from django.db.models import Sum, F

@login_required
def transfer_list(request):
    """List transfers based on user permissions"""
    if request.user.is_manager() or request.user.is_superuser:
        transfers = Transfer.objects.all().select_related('agent', 'validated_by', 'executed_by')
    else:
        transfers = Transfer.objects.filter(agent=request.user).select_related('agent', 'validated_by', 'executed_by')

    # Filter by status if specified
    status = request.GET.get('status')
    if status:
        transfers = transfers.filter(status=status)

    transfers = transfers.order_by('-created_at')

    context = {
        'transfers': transfers,
        'current_status': status,
        'status_choices': TRANSFER_STATUS,
    }

    return render(request, 'transfers/transfer_list.html', context)


@login_required
def create_transfer(request):
    """Create new transfer - agents and managers"""
    if request.method == 'POST':
        form = TransferForm(request.POST)
        if form.is_valid():
            try:

                transfer = form.save(commit=False)
                transfer.agent = request.user
                transfer.save()

                log_user_activity(
                        request.user,
                        'transfer_created',
                        {'transfer_id': transfer.id, 'beneficiary': transfer.beneficiary_name},
                        request
                )

                messages.success(request, f'Transfer #{transfer.id} created successfully')
                return redirect('transfer_detail', transfer_id=transfer.id)
            except ValidationError as e:
                messages.error(request, str(e))
                log_user_activity(
                    request.user,
                    'Transfer_creation_failed',
                    {'error': str(e), 'form_data': form.cleaned_data},
                    request
                )
        else:
            print("Form errors:", form.errors)
    else:
        form = TransferForm()

    return render(request, 'transfers/create_transfer.html', {'form': form})


@login_required
def transfer_detail(request, transfer_id):
    """View transfer details"""
    transfer = get_object_or_404(Transfer, id=transfer_id)

    # Check permissions
    if not (request.user.is_manager() or request.user.is_superuser) and transfer.agent != request.user:
        return HttpResponseForbidden("You can only view your own transfers")

    # Get commission info if exists
    commission = getattr(transfer, 'commission', None)

    context = {
        'transfer': transfer,
        'commission': commission,
        'can_validate': transfer.can_be_validated_by(request.user),
        'can_execute': transfer.can_be_executed_by(request.user),
    }

    return render(request, 'transfers/transfer_detail.html', context)


@login_required
@require_http_methods(["POST"])
def validate_transfer(request, transfer_id):
    """Validate transfer - managers and superusers only"""
    if not (request.user.is_manager() or request.user.is_superuser):
        return JsonResponse({'error': 'Access denied'}, status=403)

    transfer = get_object_or_404(Transfer, id=transfer_id)

    if not transfer.can_be_validated_by(request.user):
        return JsonResponse({
            'error': f'Transfer cannot be validated. Current status: {transfer.get_status_display()}. Required status: PENDING.'
        }, status=400)

    action = request.POST.get('action')  # 'validate' or 'reject'
    comment = request.POST.get('comment', '')

    if action == 'validate':
        transfer.status = 'VALIDATED'
        transfer.validated_by = request.user
        transfer.validated_at = timezone.now()
        transfer.validation_comment = comment
        transfer.save()

        # Calculate and create commission
        create_commission_for_transfer(transfer)

        log_user_activity(
                request.user,
                'transfer_validated',
                {'transfer_id': transfer.id, 'beneficiary': transfer.beneficiary_name},
                request
        )

        messages.success(request, f'Transfer #{transfer.id} validated successfully')

    elif action == 'reject':
        transfer.status = 'CANCELED'
        transfer.validated_by = request.user
        transfer.validated_at = timezone.now()
        transfer.validation_comment = comment
        transfer.save()

        log_user_activity(
                request.user,
                'transfer_rejected',
                {'transfer_id': transfer.id, 'beneficiary': transfer.beneficiary_name, 'reason': comment},
                request
        )

        messages.warning(request, f'Transfer #{transfer.id} rejected')

    return JsonResponse({'success': True, 'new_status': transfer.get_status_display()})


@login_required
@require_http_methods(["POST"])
def execute_transfer(request, transfer_id):
    """Execute transfer - managers and superusers only"""
    if not (request.user.is_manager() or request.user.is_superuser):
        return JsonResponse({'error': 'Access denied'}, status=403)

    transfer = get_object_or_404(Transfer, id=transfer_id)

    if not transfer.can_be_executed_by(request.user):
        return JsonResponse({
            'error': f'Transfer cannot be executed. Current status: {transfer.get_status_display()}. Required status: VALIDATED.'
        }, status=400)

    comment = request.POST.get('comment', '').strip()

    try:
        transfer.status = 'COMPLETED'
        transfer.executed_by = request.user
        transfer.executed_at = timezone.now()
        transfer.execution_comment = comment
        transfer.save()

        log_user_activity(
                request.user,
                'transfer_executed',
                {
                    'transfer_id': transfer.id,
                    'beneficiary': transfer.beneficiary_name,
                    'amount': str(transfer.amount),
                    'currency': transfer.sent_currency
                },
                request
        )

        messages.success(request, f'Transfer #{transfer.id} completed successfully')

        return JsonResponse({
            'success': True,
            'new_status': transfer.get_status_display(),
            'message': f'Transfer #{transfer.id} completed successfully'
        })

    except Exception as e:
        return JsonResponse({'error': f'Failed to complete transfer: {str(e)}'}, status=500)


@login_required
def pending_transfers(request):
    """List pending transfers for managers and superusers"""
    if not (request.user.is_manager() or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")

    pending_transfers = Transfer.objects.filter(status='PENDING').select_related('agent').order_by('-created_at')

    return render(request, 'transfers/pending_transfers.html', {'transfers': pending_transfers})


@login_required
def commission_config_list(request):
    """List commission configurations - managers and superusers only"""
    if not (request.user.is_manager() or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")

    configs = CommissionConfig.objects.filter(manager=request.user).order_by('currency', 'min_amount')

    return render(request, 'transfers/commission_config_list.html', {'configs': configs})


@login_required
def create_commission_config(request):
    """Create commission configuration - managers and superusers only"""
    if not (request.user.is_manager() or request.user.is_superuser):
        return HttpResponseForbidden("Access denied")

    if request.method == 'POST':
        form = CommissionConfigForm(request.POST)
        if form.is_valid():
            config = form.save(commit=False)
            config.manager = request.user
            config.save()

            log_user_activity(
                    request.user,
                    'commission_config_created',
                    {'currency': config.currency, 'rate': str(config.commission_rate)},
                    request
            )

            messages.success(request, 'Commission configuration created successfully')
            return redirect('commission_config_list')
    else:
        form = CommissionConfigForm()

    return render(request, 'transfers/create_commission_config.html', {'form': form})


@login_required
@require_http_methods(["POST"])
def toggle_commission_config(request, config_id):
    """Toggle commission config active status - managers and superusers only"""
    if not (request.user.is_manager() or request.user.is_superuser):
        return JsonResponse({'error': 'Access denied'}, status=403)

    config = get_object_or_404(CommissionConfig, id=config_id, manager=request.user)

    config.active = not config.active
    config.save()

    log_user_activity(
            request.user,
            'commission_config_toggled',
            {
                'config_id': config.id,
                'currency': config.currency,
                'new_status': 'active' if config.active else 'inactive'
            },
            request
    )

    return JsonResponse({
        'success': True,
        'new_status': config.active,
        'status_text': 'Active' if config.active else 'Inactive'
    })


@login_required
@require_http_methods(["POST"])
def update_commission_config(request, config_id):
    """Update commission config - managers and superusers only"""
    if not (request.user.is_manager() or request.user.is_superuser):
        return JsonResponse({'error': 'Access denied'}, status=403)

    config = get_object_or_404(CommissionConfig, id=config_id, manager=request.user)

    try:
        import json
        data = json.loads(request.body)

        # Update fields
        config.min_amount = float(data.get('min_amount', config.min_amount))
        config.max_amount = float(data.get('max_amount', config.max_amount))
        config.commission_rate = float(data.get('commission_rate', config.commission_rate))
        config.agent_share = float(data.get('agent_share', config.agent_share))
        config.active = data.get('active', config.active)

        # Validate
        config.full_clean()
        config.save()

        log_user_activity(
                request.user,
                'commission_config_updated',
                {
                    'config_id': config.id,
                    'currency': config.currency,
                    'commission_rate': str(config.commission_rate),
                    'agent_share': str(config.agent_share),
                    'active': config.active
                },
                request
        )

        return JsonResponse({'success': True})

    except (ValueError, ValidationError) as e:
        return JsonResponse({'error': str(e)}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)


def create_commission_for_transfer(transfer):
    """Helper function to create commission for a validated transfer"""
    # Find applicable commission config
    config = CommissionConfig.objects.filter(
            manager=transfer.validated_by,
            currency=transfer.sent_currency,
            min_amount__lte=transfer.amount,
            max_amount__gte=transfer.amount,
            active=True
    ).first()

    if config:
        commission_data = CommissionDistribution.calculate_commission(transfer, config)

        if commission_data:
            CommissionDistribution.objects.create(
                    transfer=transfer,
                    agent=transfer.agent,
                    config_used=config,
                    **commission_data
            )

@login_required
def commissions_overview(request):
    """ list current user commission for a specified period, managers can view all user's commissions"""

    user = request.user
    period = request.GET.get('period', 'month')  # 'day', 'week', 'month', 'year'

    trunc_map = {
        'day': TruncDay,
        'week': TruncWeek,
        'month': TruncMonth,
        'year': TruncYear,
    }
    trunc_function = trunc_map.get(period, TruncMonth)

    period_label_map = {
        'day': 'jour',
        'week': 'semaine',
        'month': 'mois',
        'year': 'année'
    }
    period_label = period_label_map.get(period, 'mois')

    
    # agents only see their earnings
    if not (user.is_manager() or user.is_superuser):
        commissions = (
            CommissionDistribution.objects
            .filter(agent=user)
            .annotate(period=trunc_function('created_at'))
            .values('period')
            .annotate(total=Sum('declaring_agent_amount'))
            .order_by('period')
        )
        
        detailed = (
            CommissionDistribution.objects
            .filter(agent=user)
            .select_related('transfer__validated_by', 'config_used')
            .order_by('-created_at')
        )

        context = {
            'is_manager': False,
            'period': period,
            'commissions': commissions,
            'detailed_commissions': detailed,
            'period_label': period_label,  
        }
    else:
    # Managers can visualize the commisions and all agent's earnings 
        global_commissions = (
            CommissionDistribution.objects
            .annotate(period=trunc_function('created_at'))
            .values('period')
            .annotate(
                total_agent=Sum('declaring_agent_amount'),
                total_manager=Sum('manager_amount')
            )
            .order_by('-period')
        )

        per_agent_totals = (
            CommissionDistribution.objects
            .values('agent__id', 'agent__username')
            .annotate(
                total=Sum('declaring_agent_amount'),
                total_commissions=Sum('total_commission'),
                total_manager=Sum('manager_amount')
            )
            .order_by('total')
        )
        
        detailed = (
            CommissionDistribution.objects
            .select_related('transfer__validated_by', 'config_used', 'agent')
            .order_by('-created_at')
        )

        context = {
            'is_manager': True,
            'period': period,
            'global_commissions': global_commissions,
            'per_agent_totals': per_agent_totals,
            'detailed_commissions': detailed,
            'period_label': period_label,  
        }

        
    return render(request, 'transfers/commissions.html', context)