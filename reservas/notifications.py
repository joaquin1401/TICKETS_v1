from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone

from .email_utils import send_templated_email
from .models import NotificationLog


def notify_reservation_created(ticket):
    """Notifica al creador que su ticket fue creado."""
    # evitar duplicados
    if NotificationLog.objects.filter(ticket=ticket, notification_type=NotificationLog.TYPE_CREATED).exists():
        return

    ctx = {"ticket": ticket, "usuario": ticket.id_usuario}
    subject = f"Tu reserva #{ticket.pk} fue creada"
    send_templated_email(subject, "reservas/emails/reservation_created", ctx, ticket.id_usuario.correo)
    NotificationLog.objects.create(ticket=ticket, notification_type=NotificationLog.TYPE_CREATED)


def notify_reservation_cancelled(ticket):
    """Envía correo al usuario cuando su reserva es cancelada."""
    if NotificationLog.objects.filter(ticket=ticket, notification_type=NotificationLog.TYPE_CANCELLED).exists():
        return

    ctx = {"ticket": ticket, "usuario": ticket.id_usuario}
    subject = f"Tu reserva #{ticket.pk} fue cancelada"
    send_templated_email(subject, "reservas/emails/reservation_cancelled", ctx, ticket.id_usuario.correo)
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
    else:
        subject = f"Recordatorio: Tu reserva #{ticket.pk} es hoy"
        template = "reservas/emails/reminder_same_day"

    ctx = {"ticket": ticket, "usuario": ticket.id_usuario}
    send_templated_email(subject, template, ctx, ticket.id_usuario.correo)
    NotificationLog.objects.create(ticket=ticket, notification_type=kind)
