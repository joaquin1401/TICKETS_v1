from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone

from django_q.tasks import async_task
from ..models import NotificationLog


def notify_reservation_created(ticket):
    """Notifica al creador que su ticket fue creado."""
    # evitar duplicados
    if NotificationLog.objects.filter(ticket=ticket, notification_type=NotificationLog.TYPE_CREATED).exists():
        return

    ctx = {"ticket": ticket, "usuario": ticket.id_usuario, "site_url": getattr(settings, "SITE_URL", "http://localhost:8000")}
    subject = f"Tu reserva #{ticket.pk} fue creada"
    async_task("reservas.tasks.enviar_correo_templated_async", subject, "reservas/emails/reservation_created", ctx, ticket.id_usuario.correo)
    NotificationLog.objects.create(ticket=ticket, notification_type=NotificationLog.TYPE_CREATED)


def notify_reservation_cancelled(ticket):
    """Envía correo al usuario cuando su reserva es cancelada."""
    if NotificationLog.objects.filter(ticket=ticket, notification_type=NotificationLog.TYPE_CANCELLED).exists():
        return

    ctx = {"ticket": ticket, "usuario": ticket.id_usuario, "site_url": getattr(settings, "SITE_URL", "http://localhost:8000")}
    subject = f"Tu reserva #{ticket.pk} fue cancelada"
    async_task("reservas.tasks.enviar_correo_templated_async", subject, "reservas/emails/reservation_cancelled", ctx, ticket.id_usuario.correo)
    NotificationLog.objects.create(ticket=ticket, notification_type=NotificationLog.TYPE_CANCELLED)


def send_reminder(ticket, kind):
    """Envía recordatorio y registra en NotificationLog.

    `kind` debe ser uno de NotificationLog.TYPE_REMINDER_3_DAYS o TYPE_REMINDER_SAME_DAY
    """
    if NotificationLog.objects.filter(ticket=ticket, notification_type=kind).exists():
        return

    if kind == NotificationLog.TYPE_REMINDER_3_DAYS:
        subject = f"Recordatorio: Tu reserva #{ticket.pk} en 3 días"
        template = "reservas/emails/reminder_3_days"
    elif kind == NotificationLog.TYPE_REMINDER_SAME_DAY:
        subject = f"Recordatorio: Tu reserva #{ticket.pk} es hoy"
        template = "reservas/emails/reminder_same_day"
    elif kind == NotificationLog.TYPE_REMINDER_RETURN_LATE:
        subject = f"Aviso: Demora en devolución del vehículo (Reserva #{ticket.pk})"
        template = "reservas/emails/reminder_return_late"

    ctx = {"ticket": ticket, "usuario": ticket.id_usuario, "site_url": getattr(settings, "SITE_URL", "http://localhost:8000")}
    async_task("reservas.tasks.enviar_correo_templated_async", subject, template, ctx, ticket.id_usuario.correo)
    NotificationLog.objects.create(ticket=ticket, notification_type=kind)


def notify_vehicle_inactive_cancelled(ticket, inactivo_hasta, tiene_permiso_5dias=False):
    """Notifica cancelación por baja temporal sin reasignación."""
    if NotificationLog.objects.filter(ticket=ticket, notification_type=NotificationLog.TYPE_VEHICLE_INACTIVE).exists():
        return

    ctx = {
        "ticket": ticket,
        "usuario": ticket.id_usuario,
        "inactivo_hasta": inactivo_hasta,
        "tiene_permiso_5dias": tiene_permiso_5dias,
        "site_url": getattr(settings, "SITE_URL", "http://localhost:8000")
    }
    subject = f"Aviso Importante: Reserva #{ticket.pk} Cancelada por Baja de Vehículo"
    async_task("reservas.tasks.enviar_correo_templated_async", subject, "reservas/emails/vehicle_inactive_cancelled", ctx, ticket.id_usuario.correo)
    NotificationLog.objects.create(ticket=ticket, notification_type=NotificationLog.TYPE_VEHICLE_INACTIVE)


def notify_vehicle_inactive_reassigned(ticket_original, nuevo_ticket):
    """Notifica que el ticket fue cancelado por baja temporal pero reasignado automáticamente."""
    if NotificationLog.objects.filter(ticket=ticket_original, notification_type=NotificationLog.TYPE_REASSIGNED).exists():
        return

    ctx = {
        "ticket_original": ticket_original,
        "nuevo_ticket": nuevo_ticket,
        "usuario": ticket_original.id_usuario,
        "site_url": getattr(settings, "SITE_URL", "http://localhost:8000"),
    }
    subject = f"Actualización de Reserva: Tu vehículo ha sido reasignado"
    async_task("reservas.tasks.enviar_correo_templated_async", subject, "reservas/emails/vehicle_inactive_reassigned", ctx, ticket_original.id_usuario.correo)
    NotificationLog.objects.create(ticket=ticket_original, notification_type=NotificationLog.TYPE_REASSIGNED)


def notify_priority_cancelled(ticket, tiene_permiso_5dias=False):
    """Notifica cancelación por prioridad de jerarquía con template amigable."""
    if NotificationLog.objects.filter(ticket=ticket, notification_type=NotificationLog.TYPE_PRIORITY_CANCELLED).exists():
        return

    ctx = {
        "ticket": ticket,
        "usuario": ticket.id_usuario,
        "tiene_permiso_5dias": tiene_permiso_5dias,
        "site_url": getattr(settings, "SITE_URL", "http://localhost:8000")
    }
    subject = f"⚠️ Reserva Cancelada: {ticket.id_vehiculo}"
    async_task("reservas.tasks.enviar_correo_templated_async", subject, "reservas/emails/priority_cancelled", ctx, ticket.id_usuario.correo)
    NotificationLog.objects.create(ticket=ticket, notification_type=NotificationLog.TYPE_PRIORITY_CANCELLED)


def notify_priority_reassigned(ticket_original, nuevo_ticket):
    """Notifica que el ticket fue cancelado por prioridad pero reasignado automáticamente."""
    if NotificationLog.objects.filter(ticket=ticket_original, notification_type=NotificationLog.TYPE_REASSIGNED).exists():
        return

    ctx = {
        "ticket_original": ticket_original,
        "nuevo_ticket": nuevo_ticket,
        "usuario": ticket_original.id_usuario,
        "site_url": getattr(settings, "SITE_URL", "http://localhost:8000"),
    }
    subject = f"Actualización de Reserva: Tu vehículo ha sido reasignado"
    async_task("reservas.tasks.enviar_correo_templated_async", subject, "reservas/emails/priority_reassigned", ctx, ticket_original.id_usuario.correo)
    NotificationLog.objects.create(ticket=ticket_original, notification_type=NotificationLog.TYPE_REASSIGNED)
