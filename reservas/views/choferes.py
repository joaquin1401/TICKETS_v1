"""
Vistas del panel de choferes.

Épica 8:
    - chofer_dashboard(): Panel principal del chofer.
    - aceptar_ticket(): Asignarse como conductor de un ticket.
    - finalizar_ticket(): Finalizar un viaje en curso.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from ..models import Ticket
from ._base import get_usuario_sesion, paginate_queryset, login_requerido, chofer_requerido


# ══════════════════════════════════════════════════════════════════════════════
# ÉPICA 8: GESTIÓN DE CHOFERES
# ══════════════════════════════════════════════════════════════════════════════


@login_requerido
@chofer_requerido
def chofer_dashboard(request):
    """
    Panel principal del chofer. Muestra en una sola pantalla:
      - Viajes en curso (asignados y activos)
      - Viajes de hoy (fecha de inicio = hoy, aún no iniciados)
      - Viajes futuros (aprobados sin conductor, con inicio después de hoy)
    """
    usuario = get_usuario_sesion(request)

    hoy = date.today()

    # Viajes en curso: asignados a este chofer con estado en_curso
    tickets_en_curso = (
        Ticket.objects
        .filter(estado=Ticket.ESTADO_EN_CURSO, conductor=usuario)
        .select_related('id_vehiculo')
        .order_by('hora_inicio')
    )

    # Viajes de hoy: aprobados, sin conductor, con hora_inicio en el día de hoy
    tickets_hoy = (
        Ticket.objects
        .filter(
            estado=Ticket.ESTADO_APROBADO,
            conductor__isnull=True,
            hora_inicio__date=hoy,
        )
        .select_related('id_vehiculo')
        .order_by('hora_inicio')
    )

    # Viajes futuros: aprobados, sin conductor, con hora_inicio después de hoy, y dentro de los próximos 7 días
    tickets_futuros_qs = (
        Ticket.objects
        .filter(
            estado=Ticket.ESTADO_APROBADO,
            conductor__isnull=True,
            hora_inicio__date__gt=hoy,
            hora_inicio__date__lte=hoy + timedelta(days=7),
        )
        .select_related('id_vehiculo')
        .order_by('hora_inicio')
    )
    page_obj, pagination_query = paginate_queryset(request, tickets_futuros_qs)

    context = {
        "usuario": usuario,
        "tickets_en_curso": tickets_en_curso,
        "tickets_hoy": tickets_hoy,
        "tickets_futuros": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "count_en_curso": tickets_en_curso.count(),
        "count_hoy": tickets_hoy.count(),
        "count_futuros": tickets_futuros_qs.count(),
    }
    return render(request, "reservas/tickets/chofer_dashboard.html", context)


@login_requerido
@chofer_requerido
def aceptar_ticket(request, ticket_id):
    """
    Permite a un chofer o admin asignarse como conductor a un ticket.
    """
    if request.method != "POST":
        return redirect("inicio")

    usuario = get_usuario_sesion(request)
    ticket = get_object_or_404(Ticket, pk=ticket_id)

    # Validar que el chofer no tenga ningún otro viaje en curso actualmente
    if Ticket.objects.filter(conductor=usuario, estado=Ticket.ESTADO_EN_CURSO).exclude(pk=ticket.pk).exists():
        messages.error(request, "No podés iniciar este viaje porque ya tenés otro viaje en curso. Debés finalizarlo primero.")
        if request.session.get("es_admin"):
            return redirect("monitor_tickets_activos")
        return redirect("chofer_dashboard")

    if ticket.estado == Ticket.ESTADO_APROBADO and ticket.conductor is None:
        km_inicio_str = request.POST.get("kilometraje_inicio", "").replace(',', '.')
        if not km_inicio_str:
            messages.error(request, "Debes ingresar el kilometraje de inicio para comenzar el viaje.")
            return redirect(request.META.get('HTTP_REFERER', 'inicio'))

        try:
            ticket.kilometraje_inicio = Decimal(km_inicio_str)
        except InvalidOperation:
            messages.error(request, "El kilometraje de inicio ingresado no es válido.")
            return redirect(request.META.get('HTTP_REFERER', 'inicio'))

        from django.utils import timezone
        ticket.conductor = usuario
        ticket.estado = Ticket.ESTADO_EN_CURSO
        ticket.hora_inicio_real = timezone.now()
        ticket.save(update_fields=['conductor', 'estado', 'kilometraje_inicio', 'hora_inicio_real'])
        messages.success(request, f"Te has asignado como conductor del ticket #{ticket.pk} y comenzaste el viaje.")
    else:
        messages.error(request, "El ticket no está disponible para asignación.")

    return redirect(request.META.get('HTTP_REFERER', 'chofer_dashboard'))


@login_requerido
@chofer_requerido
def finalizar_ticket(request, ticket_id):
    """
    Permite al conductor de un ticket finalizarlo.
    """
    if request.method != "POST":
        return redirect("inicio")

    usuario = get_usuario_sesion(request)
    ticket = get_object_or_404(Ticket, pk=ticket_id)

    if ticket.conductor == usuario or request.session.get("es_admin"):
        if ticket.estado == Ticket.ESTADO_EN_CURSO:
            km_fin_str = request.POST.get("kilometraje_fin", "").replace(',', '.')
            hora_fin_real_str = request.POST.get("hora_fin_real")

            if not km_fin_str or not hora_fin_real_str:
                messages.error(request, "Debes ingresar todos los datos reales (km y horarios) para finalizar.")
                return redirect(request.META.get('HTTP_REFERER', 'inicio'))

            from django.utils.dateparse import parse_time
            from django.utils import timezone
            from django.utils.timezone import make_aware, is_naive, is_aware, localtime
            from datetime import datetime

            try:
                ticket.kilometraje_fin = Decimal(km_fin_str)
                if ticket.kilometraje_fin >= Decimal('100000000') or ticket.kilometraje_fin < 0:
                    messages.error(request, "El kilometraje ingresado es inválido o demasiado grande (máximo 8 dígitos enteros).")
                    return redirect(request.META.get('HTTP_REFERER', 'inicio'))

                t_fin = parse_time(hora_fin_real_str)

                if not t_fin:
                    raise ValueError("Formato de hora inválido.")

                # Use already set hora_inicio_real or fallback to estimated
                if not ticket.hora_inicio_real:
                    ticket.hora_inicio_real = ticket.hora_inicio

                # Combine with the estimated dates
                if ticket.hora_fin:
                    fecha_fin = localtime(ticket.hora_fin).date() if is_aware(ticket.hora_fin) else ticket.hora_fin.date()
                else:
                    fecha_fin = localtime(ticket.hora_inicio).date() if is_aware(ticket.hora_inicio) else ticket.hora_inicio.date()

                dt_fin = datetime.combine(fecha_fin, t_fin)

                if is_naive(dt_fin):
                    dt_fin = make_aware(dt_fin)
                ticket.hora_fin_real = dt_fin

            except (ValueError, TypeError, InvalidOperation):
                messages.error(request, "Datos reales inválidos.")
                return redirect(request.META.get('HTTP_REFERER', 'inicio'))

            if is_naive(ticket.hora_inicio_real):
                ticket.hora_inicio_real = make_aware(ticket.hora_inicio_real)

            if ticket.hora_fin_real < ticket.hora_inicio_real:
                messages.error(request, "La hora de regreso no puede ser anterior a la hora de salida.")
                return redirect(request.META.get('HTTP_REFERER', 'inicio'))

            if ticket.kilometraje_inicio is not None and ticket.kilometraje_fin < ticket.kilometraje_inicio:
                messages.error(request, f"El kilometraje de regreso no puede ser menor al de salida ({ticket.kilometraje_inicio}).")
                return redirect(request.META.get('HTTP_REFERER', 'inicio'))

            # Validar justificación por retraso > 2h (comparando con la HORA ACTUAL de Argentina, no la ingresada)
            if ticket.hora_fin:
                now_local = localtime(timezone.now()) if is_aware(timezone.now()) else timezone.now()
                fin_local = localtime(ticket.hora_fin) if is_aware(ticket.hora_fin) else ticket.hora_fin
                retraso = now_local - fin_local
                if retraso.total_seconds() > 7200:
                    justificacion = request.POST.get("justificacion_retraso", "").strip()
                    if not justificacion:
                        messages.error(request, "El viaje finalizó con más de 2 horas de retraso real. Debe ingresar una justificación obligatoria.")
                        return redirect(request.META.get('HTTP_REFERER', 'inicio'))
                    ticket.justificacion_retraso = justificacion

            ticket.estado = Ticket.ESTADO_FINALIZADO
            ticket.save(update_fields=['estado', 'kilometraje_fin', 'hora_inicio_real', 'hora_fin_real', 'justificacion_retraso'])
            messages.success(request, f"El ticket #{ticket.pk} ha sido finalizado.")
        else:
            messages.error(request, "El ticket no está en curso.")
    else:
        messages.error(request, "No tenés permisos para finalizar este ticket.")

    return redirect(request.META.get('HTTP_REFERER', 'chofer_dashboard'))
