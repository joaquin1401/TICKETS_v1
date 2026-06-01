from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.utils import timezone
import logging

from .models import Ticket
from .notifications import notify_reservation_created, notify_reservation_cancelled

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Ticket)
def ticket_pre_save(sender, instance, **kwargs):
    """Almacena estado previo para comparar en post_save."""
    if not instance.pk:
        instance._pre_save_estado = None
        return
    try:
        old = sender.objects.get(pk=instance.pk)
        instance._pre_save_estado = old.estado
    except sender.DoesNotExist:
        instance._pre_save_estado = None


@receiver(post_save, sender=Ticket)
def ticket_post_save(sender, instance, created, **kwargs):
    # on create: notify creator
    if created:
        try:
            notify_reservation_created(instance)
        except Exception as e:
            logger.error("Error al enviar notificación de creación: %s", e)
        return

    # on update: check estado change to cancelled
    prev = getattr(instance, "_pre_save_estado", None)
    if prev != instance.estado and instance.estado == Ticket.ESTADO_CANCELADO:
        try:
            notify_reservation_cancelled(instance)
        except Exception as e:
            logger.error("Error al enviar notificación de cancelación: %s", e)
