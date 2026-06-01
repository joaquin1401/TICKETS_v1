from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q

from datetime import timedelta

from reservas.models import Ticket, NotificationLog
from reservas.notifications import send_reminder


class Command(BaseCommand):
    help = "Enviar recordatorios por correo para reservas próximas (3 días y mismo día)."

    def handle(self, *args, **options):
        now = timezone.now()
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

        self.stdout.write(self.style.SUCCESS(f"Reminders sent: 3-days={count3}, today={count_today}"))
