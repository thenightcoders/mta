import logging

logger = logging.getLogger(__name__)


def find_promotable_draft_transfers(commission_config):
    """
    Find all DRAFT transfers that can be promoted by a specific commission config.
    Useful for manual promotion and troubleshooting.
    """
    from .models import Transfer

    return Transfer.objects.filter(
            status='DRAFT',
            sent_currency=commission_config.currency,
            amount__gte=commission_config.min_amount,
            amount__lte=commission_config.max_amount
    ).select_related('agent')


def bulk_promote_draft_transfers(commission_config, promoted_by_user=None):
    """
    Manually promote all draft transfers that match a commission config.
    Returns a summary of promotions (success/failure counts).
    """
    from users.models import log_user_activity

    matching_transfers = find_promotable_draft_transfers(commission_config)

    results = {
        'total_found': len(matching_transfers),
        'promoted': [],
        'failed': []
    }

    for transfer in matching_transfers:
        try:
            transfer.promote_to_pending(promoted_by=promoted_by_user)
            results['promoted'].append({
                'id': transfer.id,
                'reference_id': transfer.reference_id,
                'amount': transfer.amount,
                'agent': transfer.agent.username if transfer.agent else 'No agent'
            })

        except Exception as e:
            results['failed'].append({
                'id': transfer.id,
                'reference_id': getattr(transfer, 'reference_id', f'T{transfer.id}'),
                'error': str(e)
            })

    # Log the manual bulk promotion
    if promoted_by_user:
        log_user_activity(
                promoted_by_user,
                'manual_bulk_promotion',
                {
                    'commission_config_id': commission_config.id,
                    'total_found': results['total_found'],
                    'promoted_count': len(results['promoted']),
                    'failed_count': len(results['failed']),
                    'promoted_transfers': [t['reference_id'] for t in results['promoted']],
                    'failed_transfers': [t['reference_id'] for t in results['failed']]
                }
        )

    return results


def notify_managers_of_draft_transfer(transfer, agent):
    """
    Service function to notify managers about draft transfer creation.
    Simple wrapper that calls the email service.
    """
    try:
        from email_service.services import notify_managers_of_draft_transfer as email_notify
        return email_notify(transfer.id, agent.id)
    except Exception as e:
        logger.error(f"Draft transfer notification service failed: {e}", exc_info=True)
        return {'success': 0, 'failed': 1, 'total': 1, 'errors': [str(e)]}


def notify_agents_of_auto_promotion(promoted_transfers_data, commission_config_id):
    """
    Service function to notify agents about auto-promotion.
    Simple wrapper that calls the email service.
    """
    try:
        from email_service.services import notify_agents_of_auto_promotion as email_notify
        return email_notify(promoted_transfers_data, commission_config_id)
    except Exception as e:
        logger.error(f"Auto-promotion notification service failed: {e}", exc_info=True)
        return {'success': 0, 'failed': 1, 'total': 1, 'errors': [str(e)]}


def notify_agent_of_manual_promotion(transfer, promoted_by_user):
    """
    Service function to notify agent about manual promotion.
    Simple wrapper that calls the email service.
    """
    try:
        from email_service.services import notify_agent_of_manual_promotion as email_notify
        return email_notify(transfer.id, promoted_by_user.id)
    except Exception as e:
        logger.error(f"Manual promotion notification service failed: {e}", exc_info=True)
        return False
