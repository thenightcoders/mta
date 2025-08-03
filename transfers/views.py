import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek, TruncYear
from django.db.utils import IntegrityError
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from users.models import User, log_user_activity
from .forms import CommissionConfigForm, TransferForm
from .models import CommissionConfig, CommissionDistribution, TRANSFER_STATUS, Transfer
from .services import bulk_promote_draft_transfers

logger = __import__('logging').getLogger(__name__)

@login_required
def transfer_list(request):
    """List transfers based on user permissions"""
    if request.user.is_manager():
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

                # Check if commission config exists for this transfer
                commission_config = CommissionConfig.objects.filter(
                        currency=transfer.sent_currency,
                        min_amount__lte=transfer.amount,
                        max_amount__gte=transfer.amount,
                        active=True
                ).first()

                if commission_config:
                    # Commission config exists - transfer can go to PENDING
                    transfer.status = 'PENDING'
                    transfer.save()

                    log_user_activity(
                            request.user,
                            'transfer_created',
                            {
                                'transfer_id': transfer.id,
                                'reference_id': transfer.reference_id,
                                'beneficiary': transfer.beneficiary_name,
                                'amount': str(transfer.amount),
                                'currency': transfer.sent_currency,
                                'status': 'PENDING',
                                'commission_config_available': True
                            },
                            request
                    )

                    messages.success(
                            request,
                            f'Transfer {transfer.reference_id} créé avec succès et mis en attente de validation.'
                    )
                else:
                    # No commission config - transfer stays in DRAFT
                    transfer.status = 'DRAFT'
                    transfer.save()

                    log_user_activity(
                            request.user,
                            'transfer_created_as_draft',
                            {
                                'transfer_id': transfer.id,
                                'reference_id': transfer.reference_id,
                                'beneficiary': transfer.beneficiary_name,
                                'amount': str(transfer.amount),
                                'currency': transfer.sent_currency,
                                'status': 'DRAFT',
                                'commission_config_available': False
                            },
                            request
                    )

                    if request.user.is_manager():
                        # Manager created draft - show them the issue
                        messages.warning(
                                request,
                                f'Transfer {transfer.reference_id} créé en brouillon. '
                                f'Aucune configuration de commission trouvée pour {transfer.amount} {transfer.sent_currency}. '
                                f'Veuillez configurer les commissions puis promouvoir ce transfert.'
                        )
                    else:
                        # Agent created draft - notify managers will be contacted
                        messages.warning(
                                request,
                                f'Transfer {transfer.reference_id} créé en brouillon car aucune configuration de commission '
                                f'n\'existe pour {transfer.amount} {transfer.sent_currency}. '
                                f'Les managers ont été notifiés et le transfert sera automatiquement traité une fois la '
                                f'configuration ajoutée.'
                        )

                        try:
                            from .services import notify_managers_of_draft_transfer
                            notify_managers_of_draft_transfer(transfer, request.user)
                        except Exception as e:
                            # Don't break transfer creation if email fails
                            logger.warning(f"Email notification failed for draft transfer: {e}")

                return redirect('transfer_detail', transfer_id=transfer.id)

            except ValidationError as e:
                messages.error(request, str(e))
                log_user_activity(
                        request.user,
                        'transfer_creation_failed',
                        {'error': str(e), 'form_data': form.cleaned_data},
                        request
                )
        else:
            print("Form errors:", form.errors)
    else:
        form = TransferForm()

    # Get available commission configs for preview
    commission_configs = CommissionConfig.objects.filter(active=True).order_by('currency', 'min_amount')

    context = {
        'form': form,
        'commission_configs': commission_configs,
    }

    return render(request, 'transfers/create_transfer.html', context)


@login_required
@require_http_methods(["GET"])
def check_promotable_transfers(request, config_id):
    """
    Check how many draft transfers can be promoted by a specific commission config.
    Returns count without actually promoting anything.
    """
    if not request.user.is_manager():
        return JsonResponse({'error': 'Access denied'}, status=403)

    commission_config = get_object_or_404(CommissionConfig, id=config_id, manager=request.user)

    try:
        # Find matching draft transfers
        matching_transfers = Transfer.objects.filter(
                status='DRAFT',
                sent_currency=commission_config.currency,
                amount__gte=commission_config.min_amount,
                amount__lte=commission_config.max_amount
        ).select_related('agent')

        # Build response with transfer details for preview
        transfer_details = []
        for transfer in matching_transfers[:5]:  # Limit to first 5 for preview
            transfer_details.append({
                'reference_id': transfer.reference_id,
                'amount': str(transfer.amount),
                'beneficiary': transfer.beneficiary_name,
                'agent': transfer.agent.username if transfer.agent else 'No agent',
                'created_at': transfer.created_at.strftime('%d/%m/%Y %H:%M')
            })

        return JsonResponse({
            'success': True,
            'count': len(matching_transfers),
            'transfers_preview': transfer_details,
            'has_more': len(matching_transfers) > 5,
            'config_details': {
                'currency': commission_config.currency,
                'min_amount': str(commission_config.min_amount),
                'max_amount': str(commission_config.max_amount),
                'commission_amount': str(commission_config.commission_amount)
            }
        })

    except Exception as e:
        return JsonResponse({'error': f'Check failed: {str(e)}'}, status=500)

@login_required
@require_http_methods(["POST"])
def bulk_promote_by_config(request, config_id):
    """
    Manual bulk promotion endpoint for managers when auto-promotion fails.
    """
    if not request.user.is_manager():
        return JsonResponse({'error': 'Access denied'}, status=403)

    commission_config = get_object_or_404(CommissionConfig, id=config_id, manager=request.user)

    try:
        results = bulk_promote_draft_transfers(commission_config, promoted_by_user=request.user)

        if results['promoted']:
            messages.success(
                    request,
                    f"Promu {len(results['promoted'])} transferts avec succès. "
                    + (f"{len(results['failed'])} échecs." if results['failed'] else "")
            )
        else:
            messages.info(request, "Aucun transfert à promouvoir trouvé.")

        if results['failed']:
            messages.warning(
                    request,
                    f"Échec de promotion pour {len(results['failed'])} transferts. Vérifiez les logs."
            )

        return JsonResponse({
            'success': True,
            'promoted_count': len(results['promoted']),
            'failed_count': len(results['failed']),
            'details': results
        })

    except Exception as e:
        return JsonResponse({'error': f'Bulk promotion failed: {str(e)}'}, status=500)


@login_required
@require_http_methods(["POST"])
def promote_draft_transfer(request, transfer_id):
    """Promote transfer from DRAFT to PENDING"""
    transfer = get_object_or_404(Transfer, id=transfer_id)

    # Check permissions
    if not transfer.can_be_promoted_by(request.user):
        return JsonResponse({'error': 'Permission denied or transfer cannot be promoted'}, status=403)

    try:
        transfer.promote_to_pending(promoted_by=request.user)

        log_user_activity(
                request.user,
                'transfer_promoted_to_pending',
                {
                    'transfer_id': transfer.id,
                    'reference_id': transfer.reference_id,
                    'from_status': 'DRAFT',
                    'to_status': 'PENDING'
                },
                request
        )

        messages.success(request, f'Transfer {transfer.reference_id} promu en attente de validation.')

        try:
            from .services import notify_agent_of_manual_promotion
            notify_agent_of_manual_promotion(transfer, request.user)
        except Exception as e:
            # Don't break the promotion if email fails
            logger.warning(f"Email notification failed for manual promotion: {e}")

        return JsonResponse({
            'success': True,
            'new_status': transfer.get_status_display(),
            'message': f'Transfer {transfer.reference_id} promu avec succès'
        })

    except ValidationError as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
def draft_transfers(request):
    """List draft transfers based on user permissions"""
    if request.user.is_manager():
        # Managers see all draft transfers
        transfers = Transfer.objects.filter(status='DRAFT').select_related('agent').order_by('-created_at')
        template_context = {
            'is_manager_view': True,
            'title': 'Tous les Transferts en Brouillon'
        }
    else:
        # Agents see only their own draft transfers
        transfers = Transfer.objects.filter(
                status='DRAFT',
                agent=request.user
        ).select_related('agent').order_by('-created_at')
        template_context = {
            'is_manager_view': False,
            'title': 'Mes Transferts en Brouillon'
        }

    context = {
        'transfers': transfers,
        **template_context
    }

    return render(request, 'transfers/draft_transfers.html', context)


@login_required
def transfer_detail(request, transfer_id):
    """View transfer details"""
    transfer = get_object_or_404(Transfer, id=transfer_id)

    # Check permissions
    if not request.user.is_manager() and transfer.agent != request.user:
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
    if not request.user.is_manager():
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
    if not request.user.is_manager():
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
    if not request.user.is_manager():
        return HttpResponseForbidden("Access denied")

    transfers_pending = Transfer.objects.filter(status='PENDING').select_related('agent').order_by('-created_at')
    total_amount = transfers_pending.aggregate(total=Sum('amount'))['total'] or 0
    return render(request, 'transfers/pending_transfers.html',
                  {
                      'transfers': transfers_pending,
                      'total_amount': total_amount,
                  })


@login_required
def commission_config_list(request):
    """List commission configurations - managers and superusers only"""
    if not request.user.is_manager():
        return HttpResponseForbidden("Access denied")

    configs = CommissionConfig.objects.filter(manager=request.user).order_by('currency', 'min_amount')

    return render(request, 'transfers/commission_config_list.html', {'configs': configs})


@login_required
def create_commission_config(request):
    """Create commission configuration - managers and superusers only"""
    if not request.user.is_manager():
        return HttpResponseForbidden("Access denied")

    if request.method == 'POST':
        form = CommissionConfigForm(request.POST)
        if form.is_valid():
            try:
                # Check for existing config with same parameters
                existing_config = CommissionConfig.objects.filter(
                        manager=request.user,
                        currency=form.cleaned_data['currency'],
                        min_amount=form.cleaned_data['min_amount'],
                        max_amount=form.cleaned_data['max_amount'],
                        active=True
                ).first()

                if existing_config:
                    messages.error(
                            request,
                            f'Une configuration active existe déjà pour {form.cleaned_data["min_amount"]}-{form.cleaned_data["max_amount"]} {form.cleaned_data["currency"]}. '
                            f'Désactivez-la d\'abord ou modifiez la plage de montants.'
                    )
                    return render(request, 'transfers/create_commission_config.html', {'form': form})

                config = form.save(commit=False)
                config.manager = request.user
                config.save()

                log_user_activity(
                        request.user,
                        'commission_config_created',
                        {
                            'currency': config.currency,
                            'amount_range': f'{config.min_amount}-{config.max_amount}',
                            'commission_amount': str(config.commission_amount)
                        },
                        request
                )

                messages.success(request, 'Configuration de commission créée avec succès')
                return redirect('commission_config_list')

            except IntegrityError as e:
                messages.error(
                        request,
                        'Conflit de configuration : cette plage de montants existe déjà pour cette devise. '
                        'Veuillez utiliser une plage différente.'
                )
                log_user_activity(
                        request.user,
                        'commission_config_creation_failed',
                        {'error': 'IntegrityError - duplicate range', 'form_data': form.cleaned_data},
                        request
                )
            except ValidationError as e:
                messages.error(request, str(e))
                log_user_activity(
                        request.user,
                        'commission_config_creation_failed',
                        {'error': str(e), 'form_data': form.cleaned_data},
                        request
                )
    else:
        form = CommissionConfigForm()

    return render(request, 'transfers/create_commission_config.html', {'form': form})


@login_required
@require_http_methods(["POST"])
def toggle_commission_config(request, config_id):
    """Toggle commission config active status - managers and superusers only"""
    if not request.user.is_manager():
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
    if not request.user.is_manager():
        return JsonResponse({'error': 'Access denied'}, status=403)

    config = get_object_or_404(CommissionConfig, id=config_id, manager=request.user)

    try:
        import json
        data = json.loads(request.body)

        # Update fields
        config.min_amount = float(data.get('min_amount', config.min_amount))
        config.max_amount = float(data.get('max_amount', config.max_amount))
        config.commission_amount = float(data.get('commission_amount', config.commission_amount))
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
                    'commission_amount': str(config.commission_amount),
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
    # Find applicable commission config for the transfer currency and amount
    config = CommissionConfig.objects.filter(
            manager=transfer.validated_by,
            currency=transfer.sent_currency,  # Commission config must match transfer currency
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
            return True
    return False


@login_required
def get_commission_preview(request):
    """AJAX endpoint to get commission preview for transfer creation"""
    if request.method == 'GET':
        amount = request.GET.get('amount')
        currency = request.GET.get('currency')

        if not amount or not currency:
            return JsonResponse({'error': 'Amount and currency required'})

        try:
            amount = float(amount)
        except ValueError:
            return JsonResponse({'error': 'Invalid amount'})

        # Find applicable commission config
        config = CommissionConfig.objects.filter(
                currency=currency,
                min_amount__lte=amount,
                max_amount__gte=amount,
                active=True
        ).first()

        if config:
            # Calculate commission preview
            total_commission = config.commission_amount
            agent_amount = (total_commission * config.agent_share) / 100
            manager_amount = total_commission - agent_amount

            return JsonResponse({
                'success': True,
                'config_found': True,
                'total_commission': float(total_commission),
                'agent_amount': float(agent_amount),
                'manager_amount': float(manager_amount),
                'agent_share_percent': float(config.agent_share),
                'currency': currency,
                'range': f"{config.min_amount} - {config.max_amount}",
            })
        else:
            return JsonResponse({
                'success': True,
                'config_found': False,
                'message': f'Aucune configuration de commission pour {amount} {currency}'
            })

    return JsonResponse({'error': 'Method not allowed'}, status=405)


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
    if not user.is_manager():
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


@login_required
def clear_commissions(request):
    """Update commission config - managers and superusers only"""
    if not request.user.is_manager():
        return JsonResponse({'error': 'Access denied'}, status=403)

    agents = User.objects.filter()

    if request.method == 'POST':
        mode = request.POST.get('mode')
        agent_id = request.POST.get('agent')
        date_str = request.POST.get('date')  # pour jour/semaine
        month_str = request.POST.get('month')  # pour mois
        year_str = request.POST.get('year')  # pour année
        commission_id = request.POST.get('commission_id')

        qs = CommissionDistribution.objects.all()

        # Filtrer par agent
        if agent_id:
            qs = qs.filter(agent__id=agent_id)

        # Supprimer par ID
        if commission_id:
            qs = qs.filter(id=commission_id)
            count = qs.count()
            qs.delete()
            messages.success(request, f"{count} commission(s) supprimée(s) par ID.")
            return redirect('commissions_overview')

        # Supprimer selon le mode
        if mode == 'day' and date_str:
            date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            qs = qs.filter(created_at__date=date)

        elif mode == 'week' and date_str:
            date = datetime.datetime.strptime(date_str, '%Y-%m-%d')
            year, week, _ = date.isocalendar()
            qs = qs.filter(created_at__iso_year=year, created_at__week=week)

        elif mode == 'month' and month_str:
            year, month = map(int, month_str.split('-'))
            qs = qs.filter(created_at__year=year, created_at__month=month)

        elif mode == 'year' and year_str:
            qs = qs.filter(created_at__year=int(year_str))

        count = qs.count()
        qs.delete()
        messages.success(request, f"{count} commission(s) supprimée(s).")
        return redirect('commissions_overview')

    return render(request, 'transfers/commissions_clear_form.html', {'agents': agents})
