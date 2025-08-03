import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CommissionConfig

logger = logging.getLogger(__name__)


@receiver(post_save, sender=CommissionConfig)
def auto_promote_draft_transfers(sender, instance, created, **kwargs):
    """
    Auto-promote DRAFT transfers to PENDING when a matching CommissionConfig is created or activated.
    """
    # Import here to avoid circular imports
    from .models import Transfer
    from users.signals import safe_log_activity  # Import the logging function

    # Only trigger on:
    # 1. New commission config creation (created=True)
    # 2. Existing config being activated (active=True, and it was inactive before)
    if not (created or instance.active):
        return

    try:
        # Find all DRAFT transfers that match this commission config
        matching_transfers = Transfer.objects.filter(
                status='DRAFT',
                sent_currency=instance.currency,
                amount__gte=instance.min_amount,
                amount__lte=instance.max_amount
        ).select_related('agent')

        promoted_count = 0
        failed_promotions = []
        promoted_transfers_data = []  #Collect data for email notifications

        for transfer in matching_transfers:
            try:
                # Use the existing promote_to_pending method which has all the validation
                transfer.promote_to_pending(promoted_by=None)  # System promotion, no specific user
                promoted_count += 1

                # Collect promoted transfer data for email notifications
                promoted_transfers_data.append({
                    'id': transfer.id,
                    'reference_id': transfer.reference_id,
                    'amount': str(transfer.amount),
                    'beneficiary': transfer.beneficiary_name,
                    'agent': transfer.agent.username if transfer.agent else 'No agent'
                })

                # Log the auto-promotion for audit
                safe_log_activity(
                        'auto_promoted',
                        {
                            'transfer_id': transfer.id,
                            'reference_id': transfer.reference_id,
                            'commission_config_id': instance.id,
                            'amount': str(transfer.amount),
                            'currency': transfer.sent_currency,
                            'agent_username': transfer.agent.username if transfer.agent else 'No agent',
                            'config_manager': instance.manager.username,
                            'from_status': 'DRAFT',
                            'to_status': 'PENDING'
                        }
                )

            except Exception as e:
                # Log individual transfer promotion failures but don't break the whole process
                failed_promotions.append({
                    'transfer_id': transfer.id,
                    'reference_id': getattr(transfer, 'reference_id', f'T{transfer.id}'),
                    'error': str(e)
                })
                logger.warning(f"Failed to auto-promote transfer {transfer.id}: {e}")

        # Send email notifications to agents if transfers were promoted
        if promoted_transfers_data:
            try:
                from .services import notify_agents_of_auto_promotion
                notify_agents_of_auto_promotion(promoted_transfers_data, instance.id)
            except Exception as e:
                # Don't break the promotion if email fails
                logger.warning(f"Email notification failed for auto-promotion: {e}")

        # Log summary of the auto-promotion batch
        if promoted_count > 0 or failed_promotions:
            safe_log_activity(
                    'auto_promotion_batch',
                    {
                        'commission_config_id': instance.id,
                        'config_manager': instance.manager.username,
                        'currency': instance.currency,
                        'min_amount': str(instance.min_amount),
                        'max_amount': str(instance.max_amount),
                        'promoted_count': promoted_count,
                        'failed_count': len(failed_promotions),
                        'failed_transfers': failed_promotions,
                        'email_notifications_sent': len(promoted_transfers_data) > 0  # Track email status
                    }
            )

        if promoted_count > 0:
            logger.info(f"Auto-promoted {promoted_count} transfers due to new commission config {instance.id}")

        if failed_promotions:
            logger.warning(f"Failed to auto-promote {len(failed_promotions)} transfers for config {instance.id}")

    except Exception as e:
        # Never let auto-promotion break commission config creation
        logger.error(f"Auto-promotion failed for commission config {instance.id}: {e}", exc_info=True)

        # Log the failure for troubleshooting
        safe_log_activity(
                'auto_promotion_failed',
                {
                    'commission_config_id': instance.id,
                    'config_manager': instance.manager.username,
                    'error': str(e)
                }
        )
