"""
Vistas de tickets para el usuario normal.

Épica 2:
    - HU 2.1: inicio() — formulario de reserva, calendario y timeline.
    - HU 2.2: historial() — historial de tickets del usuario.
    - HU 2.3: detalle_ticket() — detalle de un ticket.
    - HU 2.4: cancelar_ticket() — cancelación de un ticket propio.
"""

import calendar
from datetime import date, timedelta, datetime, time

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q

from ..models import Vehiculo, Ticket, Cargo, ConfiguracionGlobal, Feriado
from ..forms import TicketForm, FiltroTicketsForm
from ..utils.services import crear_ticket_con_reglas, ResultadoCreacion, get_tickets_del_mes, get_tickets_del_dia
from ._base import get_usuario_sesion, paginate_queryset, login_requerido, sin_chofer_requerido


# ══════════════════════════════════════════════════════════════════════════════
# ÉPICA 2: INICIO Y TICKETS (USUARIO NORMAL)
# ══════════════════════════════════════════════════════════════════════════════
# HU 2.1: Inicio con formulario rápido de reserva
# HU 2.2: Historial de tickets
# HU 2.3: Detalle de ticket


@login_requerido
@sin_chofer_requerido
def inicio(request):
    """
    Vista de inicio principal del usuario (HU 2.1).
    Muestra formulario de reserva rápida, calendario y timeline.
    """
    usuario = get_usuario_sesion(request)
    es_admin = usuario.id_cargo.prioridad == 0
    es_usuario_general = usuario.id_cargo.nombre == Cargo.USUARIO
    form = TicketForm(es_admin=es_admin, es_usuario_general=es_usuario_general, usuario=usuario)

    if request.method == "POST":
        form = TicketForm(request.POST, es_admin=es_admin, es_usuario_general=es_usuario_general, usuario=usuario)
        if form.is_valid():
            cd = form.cleaned_data
            hora_fin = cd.get("hora_fin") or (cd["hora_inicio"] + timedelta(hours=2))

            resultado = crear_ticket_con_reglas(
                usuario=usuario,
                vehiculo=cd["id_vehiculo"],
                hora_inicio=cd["hora_inicio"],
                hora_fin=hora_fin,
                destino=cd["destino"],
                cant_pasajeros=cd["cant_pasajeros"],
                descripcion=cd.get("descripcion", ""),
                requiere_chofer=cd.get("requiere_chofer", False),
            )

            if resultado.exito:
                if resultado.estado == ResultadoCreacion.SOBRESCRITO:
                    messages.warning(request, resultado.mensaje, extra_tags="clear_draft")
                else:
                    messages.success(request, resultado.mensaje, extra_tags="clear_draft")
                return redirect("historial")
            else:
                messages.error(request, resultado.mensaje)

    # Lógica de calendario y timeline
    vehiculo_id = request.GET.get("vehiculo")
    anio = int(request.GET.get("anio", date.today().year))
    mes = int(request.GET.get("mes", date.today().month))
    dia_str = request.GET.get("dia")

    vehiculo_cal = None
    dias_con_reservas = set()
    tickets_dia = []
    margenes_dia = []
    fecha_timeline = None
    horas = []
    page_obj = None
    pagination_query = ""
    total_tickets = 0

    if vehiculo_id:
        try:
            vehiculo_cal = Vehiculo.objects.get(pk=vehiculo_id, activo=True)
            if request.method == "GET":
                form = TicketForm(initial={"id_vehiculo": vehiculo_cal}, es_admin=es_admin, es_usuario_general=es_usuario_general)

            tickets_mes = get_tickets_del_mes(vehiculo_cal, anio, mes)
            dias_con_reservas = set()
            for t in tickets_mes:
                start_date = t.hora_inicio.date()
                end_date = t.hora_fin.date() if t.hora_fin else start_date
                curr = start_date
                while curr <= end_date:
                    if curr.month == mes and curr.year == anio:
                        dias_con_reservas.add(curr)
                    curr += timedelta(days=1)

            if dia_str:
                dia = int(dia_str)
                fecha_timeline = date(anio, mes, dia)
                tickets_qs = get_tickets_del_dia(vehiculo_cal, fecha_timeline)
                page_obj, pagination_query = paginate_queryset(request, tickets_qs)
                tickets_dia = list(page_obj.object_list)

                # Calculate proportional positioning for the timeline
                # 1 hour = 60px. Timeline starts at 06:00 (which is top: 0)
                # Max visual grid ends at 23:00, which is 17 hours * 60px = 1020px height
                from django.utils import timezone
                is_tz_aware = timezone.is_aware(timezone.now())
                config_margin = ConfiguracionGlobal.get_solo()
                margen = timedelta(hours=config_margin.horas_margen_entre_reservas, minutes=config_margin.minutos_margen_entre_reservas)
                margen_minutes = int(margen.total_seconds() / 60)

                naive_start = datetime.combine(fecha_timeline, time.min)
                naive_end = datetime.combine(fecha_timeline, time.max)

                if is_tz_aware:
                    day_start = timezone.make_aware(naive_start)
                    day_end = timezone.make_aware(naive_end)
                else:
                    day_start = naive_start
                    day_end = naive_end

                margenes_dia = []

                for idx, t in enumerate(tickets_dia):
                    effective_start = max(t.hora_inicio, day_start)

                    if t.hora_fin:
                        effective_end = min(t.hora_fin, day_end)
                    else:
                        default_fin = t.hora_inicio + timedelta(hours=2)
                        effective_end = min(default_fin, day_end)

                    start_h = effective_start.hour
                    start_m = effective_start.minute

                    duration_mins = int((effective_end - effective_start).total_seconds() / 60)

                    # Cap start time to 06:00 minimum
                    if start_h < 6:
                        mins_cortados = ((6 - start_h) * 60) - start_m
                        start_h = 6
                        start_m = 0
                        duration_mins -= mins_cortados

                    t.top_px = ((start_h - 6) * 60) + start_m

                    # Cap height so it doesn't overflow past 23:00 (1020px total height)
                    if duration_mins <= 0:
                        t.height_px = 0
                    else:
                        max_allowed_height = 1020 - t.top_px
                        t.height_px = min(duration_mins, max_allowed_height) if max_allowed_height > 0 else 0

                    # Calculate margin blocks (gray areas before and after ticket)
                    if margen_minutes > 0:
                        # 1. Margin BEFORE ticket
                        margin_start_before = effective_start - margen
                        margin_end_before = effective_start

                        if margin_end_before > day_start:
                            m_start = max(margin_start_before, day_start)
                            m_end = min(margin_end_before, day_end)

                            m_start_h = m_start.hour
                            m_start_m = m_start.minute
                            m_duration = int((m_end - m_start).total_seconds() / 60)

                            if m_start_h < 6:
                                mins_cortados = ((6 - m_start_h) * 60) - m_start_m
                                m_start_h = 6
                                m_start_m = 0
                                m_duration -= mins_cortados

                            m_top_px = ((m_start_h - 6) * 60) + m_start_m

                            if m_duration > 0 and m_top_px >= 0:
                                max_margin_height = 1020 - m_top_px
                                m_duration = min(m_duration, max_margin_height)
                                margenes_dia.append({
                                    "top_px": m_top_px,
                                    "height_px": m_duration,
                                })

                        # 2. Margin AFTER ticket
                        if t.hora_fin:
                            margin_start_after = effective_end
                            margin_end_after = effective_end + margen

                            if margin_start_after < day_end:
                                m_start = max(margin_start_after, day_start)
                                m_end = min(margin_end_after, day_end)

                                m_start_h = m_start.hour
                                m_start_m = m_start.minute
                                m_duration = int((m_end - m_start).total_seconds() / 60)

                                if m_start_h < 6:
                                    mins_cortados = ((6 - m_start_h) * 60) - m_start_m
                                    m_start_h = 6
                                    m_start_m = 0
                                    m_duration -= mins_cortados

                                m_top_px = ((m_start_h - 6) * 60) + m_start_m

                                if m_duration > 0 and m_top_px >= 0:
                                    max_margin_height = 1020 - m_top_px
                                    m_duration = min(m_duration, max_margin_height)
                                    margenes_dia.append({
                                        "top_px": m_top_px,
                                        "height_px": m_duration,
                                    })

                horas = ["06", "07", "08", "09", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22"]
                total_tickets = page_obj.paginator.count
        except (Vehiculo.DoesNotExist, ValueError):
            pass

    cal = calendar.monthcalendar(anio, mes)
    nombre_mes = date(anio, mes, 1).strftime("%B %Y").capitalize()

    config = ConfiguracionGlobal.get_solo()
    dias_anticipacion = config.dias_anticipacion_reservas
    dias_cancelacion = config.dias_anticipacion_cancelacion
    dias_maximos = config.dias_maximo_anticipacion_reservas
    from django.utils import timezone
    fecha_minima = timezone.now().date() + timedelta(days=dias_anticipacion)
    fecha_minima_str = (timezone.now() + timedelta(days=dias_anticipacion)).strftime("%Y-%m-%dT%H:%M")

    dias_inhabilitados = []

    feriados_del_mes = Feriado.objects.filter(fecha__year=anio, fecha__month=mes).values_list('fecha__day', flat=True)
    dias_feriados = list(feriados_del_mes)

    for d in range(1, 32):
        try:
            curr_date = date(anio, mes, d)
            if not es_admin and curr_date < fecha_minima:
                dias_inhabilitados.append(d)
        except ValueError:
            pass

    if mes == 1:
        mes_anterior = (anio - 1, 12)
    else:
        mes_anterior = (anio, mes - 1)
    if mes == 12:
        mes_siguiente = (anio + 1, 1)
    else:
        mes_siguiente = (anio, mes + 1)

    return render(request, "reservas/tickets/inicio.html", {
        "form": form,
        "usuario": usuario,
        "vehiculo_cal": vehiculo_cal,
        "cal": cal,
        "nombre_mes": nombre_mes,
        "anio": anio,
        "mes": mes,
        "dias_con_reservas": dias_con_reservas,
        "mes_anterior": mes_anterior,
        "mes_siguiente": mes_siguiente,
        "tickets_dia": tickets_dia,
        "margenes_dia": margenes_dia,
        "fecha_timeline": fecha_timeline,
        "horas": horas,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_tickets": total_tickets,
        "dia_seleccionado": int(dia_str) if dia_str and dia_str.isdigit() else None,
        "exclusivos_ids": list(Vehiculo.objects.filter(exclusivo_decanato=True).values_list('id', flat=True)),
        "dias_inhabilitados": dias_inhabilitados,
        "dias_feriados": dias_feriados,
        "fecha_minima_str": fecha_minima_str,
        "dias_anticipacion": dias_anticipacion,
        "dias_maximos": dias_maximos,
        "dias_cancelacion": dias_cancelacion,
    })


@login_requerido
@sin_chofer_requerido
def historial(request):
    """
    Vista del historial de tickets del usuario (HU 2.2).

    Muestra todos los tickets del usuario logueado ordenados
    por hora_inicio descendente (más recientes primero).

    Args:
        request (HttpRequest): Objeto de solicitud (GET).

    Returns:
        HttpResponse: Plantilla 'reservas/tickets/historial.html' con:
            - tickets: QuerySet de tickets del usuario.
            - usuario: Instancia del usuario logueado.
    """
    usuario = get_usuario_sesion(request)
    form = FiltroTicketsForm(request.GET or None)
    tickets_qs = Ticket.objects.filter(
        id_usuario=usuario
    ).select_related("id_vehiculo").order_by("-fecha", "-id")

    if form.is_valid():
        from django.db.models.functions import Lower

        busqueda = form.cleaned_data.get("busqueda")
        conductor = form.cleaned_data.get("conductor")
        vehiculo = form.cleaned_data.get("vehiculo")
        fecha_inicio = form.cleaned_data.get("fecha_inicio")
        fecha_fin = form.cleaned_data.get("fecha_fin")

        tickets_qs = tickets_qs.annotate(
            busq_nombre=Lower('id_usuario__nombre'),
            busq_apellido=Lower('id_usuario__apellido'),
            busq_destino=Lower('destino'),
            cond_nombre=Lower('conductor__nombre'),
            cond_apellido=Lower('conductor__apellido')
        )

        if busqueda:
            busqueda_lower = busqueda.lower()
            for palabra in busqueda_lower.split():
                tickets_qs = tickets_qs.filter(
                    Q(busq_nombre__icontains=palabra)
                    | Q(busq_apellido__icontains=palabra)
                    | Q(busq_destino__icontains=palabra)
                )
        if conductor:
            conductor_lower = conductor.lower()
            for palabra in conductor_lower.split():
                tickets_qs = tickets_qs.filter(
                    Q(cond_nombre__icontains=palabra)
                    | Q(cond_apellido__icontains=palabra)
                )
        if vehiculo:
            tickets_qs = tickets_qs.filter(id_vehiculo=vehiculo)
        if fecha_inicio:
            tickets_qs = tickets_qs.filter(hora_inicio__date__gte=fecha_inicio)
        if fecha_fin:
            tickets_qs = tickets_qs.filter(hora_inicio__date__lte=fecha_fin)

    page_obj, pagination_query = paginate_queryset(request, tickets_qs)

    return render(request, "reservas/tickets/historial.html", {
        "form": form,
        "tickets": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_tickets": page_obj.paginator.count,
        "usuario": usuario,
    })


@login_requerido
@sin_chofer_requerido
def detalle_ticket(request, ticket_id):
    """
    Vista de detalle de un ticket específico (HU 2.3).

    Muestra información completa de un ticket. Los administradores
    pueden ver cualquier ticket; usuarios normales solo sus propios.

    Args:
        request (HttpRequest): Objeto de solicitud.
        ticket_id (int): PK del ticket.

    Returns:
        HttpResponse: Plantilla 'reservas/tickets/detalle_ticket.html' con ticket.

    Raises:
        Http404: Si el ticket no existe o el usuario normal intenta
            acceder a un ticket que no es suyo.

    Autorización:
        - es_admin=True: Acceso a cualquier ticket.
        - es_admin=False: Acceso solo si id_usuario == usuario_sesion.
    """
    usuario = get_usuario_sesion(request)
    if request.session.get("es_admin"):
        ticket = get_object_or_404(Ticket, pk=ticket_id)
    else:
        ticket = get_object_or_404(Ticket, pk=ticket_id, id_usuario=usuario)

    from django.utils import timezone
    from ..models import ConfiguracionGlobal, get_localdate
    import datetime
    dias_cancelacion = ConfiguracionGlobal.get_solo().dias_anticipacion_cancelacion
    puede_cancelar = False
    
    hoy = get_localdate()
    fecha_inicio = ticket.hora_inicio.date() if hasattr(ticket.hora_inicio, 'date') else ticket.hora_inicio
    
    if ticket.estado == Ticket.ESTADO_APROBADO and fecha_inicio >= hoy + datetime.timedelta(days=dias_cancelacion):
        puede_cancelar = True

    return render(request, "reservas/tickets/detalle_ticket.html", {
        "ticket": ticket,
        "usuario": usuario,
        "puede_cancelar": puede_cancelar,
    })


@login_requerido
@sin_chofer_requerido
def cancelar_ticket(request, ticket_id):
    """
    Vista para que un usuario cancele su propio ticket (HU 2.4).

    Verifica que la petición sea POST. Delega la validación de negocio
    (5 días de antelación) a la capa de servicios.
    """
    from ..utils.services import cancelar_ticket_usuario

    if request.method != "POST":
        return redirect("inicio")

    usuario = get_usuario_sesion(request)
    ticket = get_object_or_404(Ticket, pk=ticket_id)

    exito, mensaje = cancelar_ticket_usuario(ticket, usuario)
    if exito:
        messages.success(request, mensaje)
    else:
        messages.error(request, mensaje)

    return redirect("detalle_ticket", ticket_id=ticket.pk)
