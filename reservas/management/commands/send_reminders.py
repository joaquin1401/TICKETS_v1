from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q

from datetime import timedelta

from reservas.models import Ticket, NotificationLog
from reservas.utils.notifications import send_reminder


class Command(BaseCommand):
    help = "Enviar recordatorios por correo para reservas próximas y devoluciones demoradas."

    def handle(self, *args, **options):
        from django.conf import settings
        now = timezone.localtime(timezone.now()) if settings.USE_TZ else timezone.now()
        today = now.date()
        in_3_days = (now + timedelta(days=3)).date()

        # Tickets aprobados cuya hora_inicio cae en 3 días -> enviar recordatorio 3 días
        q_3 = Ticket.objects.filter(estado=Ticket.ESTADO_APROBADO, hora_inicio__date=in_3_days)
        count3 = 0
        for t in q_3:
            if not NotificationLog.objects.filter(ticket=t, notification_type=NotificationLog.TYPE_REMINDER_3_DAYS).exists():
                send_reminder(t, NotificationLog.TYPE_REMINDER_3_DAYS)
                count3 += 1

        # Tickets aprobados cuya hora_inicio cae hoy -> enviar recordatorio mismo día
        q_today = Ticket.objects.filter(estado=Ticket.ESTADO_APROBADO, hora_inicio__date=today)
        count_today = 0
        for t in q_today:
            if not NotificationLog.objects.filter(ticket=t, notification_type=NotificationLog.TYPE_REMINDER_SAME_DAY).exists():
                send_reminder(t, NotificationLog.TYPE_REMINDER_SAME_DAY)
                count_today += 1

        # Tickets en curso con más de 1 hora de retraso
        one_hour_ago = now - timedelta(hours=1)
        q_late = Ticket.objects.filter(
            estado=Ticket.ESTADO_EN_CURSO,
            hora_fin__lt=one_hour_ago
        )
        count_late = 0
        for t in q_late:
            if not NotificationLog.objects.filter(ticket=t, notification_type=NotificationLog.TYPE_REMINDER_RETURN_LATE).exists():
                send_reminder(t, NotificationLog.TYPE_REMINDER_RETURN_LATE)
                count_late += 1

        self.stdout.write(self.style.SUCCESS(f"Reminders sent: 3-days={count3}, today={count_today}, late={count_late}"))
