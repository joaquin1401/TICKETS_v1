"""
Vistas administrativas de supervisión de tickets.

Épica 5 (tickets):
    - HU 5.3: monitor_tickets_activos() — tickets aprobados/en curso.
    - HU 5.4: historial_tickets() — tickets finalizados y cancelados.
    - descargar_historial_csv() — exportación CSV del historial.
    - crear_ticket_manual() — carga manual de un ticket por un admin.
"""

import csv
from datetime import timedelta

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from ..forms import FiltroTicketsForm, TicketManualForm
from ..models import Ticket
from ._base import (
    admin_requerido,
    get_usuario_sesion,
    login_requerido,
    paginate_queryset,
)

# ══════════════════════════════════════════════════════════════════════════════
# ÉPICA 5: GESTIÓN Y SUPERVISIÓN ADMINISTRATIVA — TICKETS
# ══════════════════════════════════════════════════════════════════════════════


@login_requerido
@admin_requerido
def monitor_tickets_activos(request):
    """
    Vista del monitor de tickets activos de la empresa (HU 5.3).

    Muestra todos los tickets aprobados con hora_inicio >= hoy,
    ordenados cronológicamente. Incluye info del usuario y vehículo.

    Args:
        request (HttpRequest): Objeto de solicitud (GET).

    Returns:
        HttpResponse: Plantilla 'reservas/tickets/tickets_activos.html' con:
            - tickets: QuerySet de tickets aprobados futuros.
            - usuario: Instancia del usuario logueado (admin).

    Optimizaciones BD:
        - .select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo")
          para evitar N+1 queries.

    Notas:
        - "Activos" = aprobados y con hora_inicio desde hoy en adelante.
        - Útil para supervisión de operaciones y conflictos en tiempo real.
    """
    form = FiltroTicketsForm(request.GET or None)
    tickets_qs = (
        Ticket.objects.filter(
            estado__in=[Ticket.ESTADO_APROBADO, Ticket.ESTADO_EN_CURSO],
            hora_inicio__gte=timezone.localdate(),
        )
        .select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo")
        .order_by("-fecha", "-id")
    )

    if form.is_valid():
        from django.db.models.functions import Lower

        busqueda = form.cleaned_data.get("busqueda")
        conductor = form.cleaned_data.get("conductor")
        vehiculo = form.cleaned_data.get("vehiculo")
        cargo = form.cleaned_data.get("cargo")
        fecha_inicio = form.cleaned_data.get("fecha_inicio")
        fecha_fin = form.cleaned_data.get("fecha_fin")

        tickets_qs = tickets_qs.annotate(
            busq_nombre=Lower("id_usuario__nombre"),
            busq_apellido=Lower("id_usuario__apellido"),
            busq_destino=Lower("destino"),
            cond_nombre=Lower("conductor__nombre"),
            cond_apellido=Lower("conductor__apellido"),
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
        if cargo:
            tickets_qs = tickets_qs.filter(id_usuario__id_cargo=cargo)
        if fecha_inicio:
            tickets_qs = tickets_qs.filter(hora_inicio__date__gte=fecha_inicio)
        if fecha_fin:
            tickets_qs = tickets_qs.filter(hora_inicio__date__lte=fecha_fin)

    page_obj, pagination_query = paginate_queryset(request, tickets_qs)
    vehiculos_en_uso = tickets_qs.values("id_vehiculo").distinct().count()

    return render(
        request,
        "reservas/tickets/tickets_activos.html",
        {
            "form": form,
            "tickets": page_obj.object_list,
            "page_obj": page_obj,
            "pagination_query": pagination_query,
            "total_tickets": page_obj.paginator.count,
            "vehiculos_en_uso": vehiculos_en_uso,
            "usuario": get_usuario_sesion(request),
        },
    )


@login_requerido
@admin_requerido
def historial_tickets(request):
    """
    Vista de historial de tickets históricos y cancelados (HU 5.4).

    Muestra todos los tickets con estado CANCELADO o con hora_inicio < hoy.
    Útil para análisis de patrones, conflictos resueltos y cancelaciones.

    Args:
        request (HttpRequest): Objeto de solicitud (GET).

    Returns:
        HttpResponse: Plantilla 'reservas/tickets/historial_tickets.html' con:
            - tickets: QuerySet de tickets históricos/cancelados.
            - usuario: Instancia del usuario logueado (admin).

    Criterios:
        - estado == CANCELADO (por sobrescritura o admin), O
        - hora_inicio < hoy (pasados).

    Notas:
        - Campo observacion permite revisar razones de cancelación.
        - Ordenados por hora_inicio descendente (más recientes primero).
    """
    form = FiltroTicketsForm(request.GET or None)
    tickets_qs = (
        Ticket.objects.filter(
            Q(estado__in=[Ticket.ESTADO_CANCELADO, Ticket.ESTADO_FINALIZADO])
            | Q(hora_inicio__lt=timezone.localdate())
        )
        .select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo")
        .order_by("-fecha", "-id")
    )

    if form.is_valid():
        from django.db.models.functions import Lower

        busqueda = form.cleaned_data.get("busqueda")
        conductor = form.cleaned_data.get("conductor")
        vehiculo = form.cleaned_data.get("vehiculo")
        cargo = form.cleaned_data.get("cargo")
        fecha_inicio = form.cleaned_data.get("fecha_inicio")
        fecha_fin = form.cleaned_data.get("fecha_fin")

        tickets_qs = tickets_qs.annotate(
            busq_nombre=Lower("id_usuario__nombre"),
            busq_apellido=Lower("id_usuario__apellido"),
            busq_destino=Lower("destino"),
            cond_nombre=Lower("conductor__nombre"),
            cond_apellido=Lower("conductor__apellido"),
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
        if cargo:
            tickets_qs = tickets_qs.filter(id_usuario__id_cargo=cargo)
        if fecha_inicio:
            tickets_qs = tickets_qs.filter(hora_inicio__date__gte=fecha_inicio)
        if fecha_fin:
            tickets_qs = tickets_qs.filter(hora_inicio__date__lte=fecha_fin)

    page_obj, pagination_query = paginate_queryset(request, tickets_qs)

    return render(
        request,
        "reservas/tickets/historial_tickets.html",
        {
            "form": form,
            "tickets": page_obj.object_list,
            "page_obj": page_obj,
            "pagination_query": pagination_query,
            "total_tickets": page_obj.paginator.count,
            "usuario": get_usuario_sesion(request),
        },
    )


@login_requerido
@admin_requerido
def descargar_historial_csv(request):
    """
    Exporta el historial de tickets a un archivo CSV descargable.
    Aplica los mismos filtros que historial_tickets().
    """
    form = FiltroTicketsForm(request.GET or None)
    tickets_qs = (
        Ticket.objects.filter(
            # Antes decía Q(estado=CANCELADO) | Q(hora_inicio__lt=...): un ticket
            # FINALIZADO con hora_inicio de hoy (ver el bug de estado_inicial
            # arreglado en services.py) no caía en ninguna de las dos condiciones
            # y quedaba afuera del CSV, aunque sí aparecía en historial_tickets()
            # - a pesar de que el docstring de esta función dice que aplica "los
            # mismos filtros". Ahora sí son literalmente los mismos.
            Q(estado__in=[Ticket.ESTADO_CANCELADO, Ticket.ESTADO_FINALIZADO])
            | Q(hora_inicio__lt=timezone.localdate())
        )
        .select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo")
        .order_by("-fecha", "-id")
    )

    if form.is_valid():
        from django.db.models.functions import Lower

        busqueda = form.cleaned_data.get("busqueda")
        conductor = form.cleaned_data.get("conductor")
        vehiculo = form.cleaned_data.get("vehiculo")
        cargo = form.cleaned_data.get("cargo")
        fecha_inicio = form.cleaned_data.get("fecha_inicio")
        fecha_fin = form.cleaned_data.get("fecha_fin")

        tickets_qs = tickets_qs.annotate(
            busq_nombre=Lower("id_usuario__nombre"),
            busq_apellido=Lower("id_usuario__apellido"),
            busq_destino=Lower("destino"),
            cond_nombre=Lower("conductor__nombre"),
            cond_apellido=Lower("conductor__apellido"),
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
        if cargo:
            tickets_qs = tickets_qs.filter(id_usuario__id_cargo=cargo)
        if fecha_inicio:
            tickets_qs = tickets_qs.filter(hora_inicio__date__gte=fecha_inicio)
        if fecha_fin:
            tickets_qs = tickets_qs.filter(hora_inicio__date__lte=fecha_fin)

    # localtime, no datetime.now(): esta última usa la hora del sistema
    # operativo (típicamente UTC en el server), no la de Argentina.
    timestamp = timezone.localtime(timezone.now()).strftime("%Y-%m-%d_%H-%M-%S")
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="historial_ticket_{timestamp}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow(
        [
            "ID",
            "Solicitante",
            "Cargo",
            "Vehiculo",
            "Destino",
            "Salida",
            "Regreso",
            "Distancia Real (km)",
            "Estado",
            "Observacion",
        ]
    )

    from django.utils.timezone import is_aware, localtime

    for t in tickets_qs:
        salida = ""
        if t.hora_inicio:
            dt = localtime(t.hora_inicio) if is_aware(t.hora_inicio) else t.hora_inicio
            salida = dt.strftime("%d/%m/%Y %H:%M")

        regreso = ""
        if t.hora_fin:
            dt = localtime(t.hora_fin) if is_aware(t.hora_fin) else t.hora_fin
            regreso = dt.strftime("%d/%m/%Y %H:%M")

        writer.writerow(
            [
                t.pk,
                t.id_usuario.nombre_completo,
                t.id_usuario.id_cargo.nombre,
                f"{t.id_vehiculo.marca} {t.id_vehiculo.modelo}",
                t.destino,
                salida,
                regreso,
                t.distancia_real if t.distancia_real is not None else "",
                t.estado,
                t.observacion,
            ]
        )

    return response


@login_requerido
@admin_requerido
def crear_ticket_manual(request):
    """
    Carga manual de un ticket por un admin: digitalizar reservas hechas
    por teléfono/papel, o backfill histórico.

    No pasa por services.crear_ticket_con_reglas() (ver docstring de
    TicketManualForm) - el admin está afirmando directamente que la
    reserva es válida. Solo se valida:
        - lo estructural (hora_fin > hora_inicio, kilometraje_fin >=
          kilometraje_inicio), en el form.
        - que no haya otro ticket ACTIVO (aprobado/en_curso) para el mismo
          vehículo en la misma franja, y solo si el ticket que se está
          creando también queda en un estado activo. Un backfill
          finalizado/cancelado no reclama la agenda del vehículo, así que
          no tiene sentido bloquearlo por "conflicto" con una reserva
          vigente de otra persona - a diferencia de crear_ticket_con_reglas,
          acá NO hay lógica de sobrescritura por jerarquía: si hay
          conflicto real, se rechaza sin más (nada de cancelar en silencio
          la reserva de otra persona y mandarle un correo de aviso).

    Usuario solicitante y conductor son opcionales: si no se especifican,
    el ticket queda a nombre del propio admin (usuario_admin) y sin
    conductor asignado.

    Notificación por correo: se omite para estados FINALIZADO/CANCELADO
    (backfill histórico - avisar "tu reserva fue creada" de un viaje que
    ya pasó hace semanas sería confuso), pero se envía normalmente para
    APROBADO/EN_CURSO, igual que cualquier otra reserva nueva.
    """
    usuario_admin = get_usuario_sesion(request)

    if request.method == "POST":
        form = TicketManualForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            id_usuario = cd.get("id_usuario") or usuario_admin
            vehiculo = cd["id_vehiculo"]
            hora_inicio = cd["hora_inicio"]
            hora_fin = cd.get("hora_fin") or (hora_inicio + timedelta(hours=2))
            estado = cd["estado"]

            if estado in (Ticket.ESTADO_APROBADO, Ticket.ESTADO_EN_CURSO):
                conflicto = (
                    Ticket.objects.filter(
                        id_vehiculo=vehiculo,
                        estado__in=[Ticket.ESTADO_APROBADO, Ticket.ESTADO_EN_CURSO],
                        hora_inicio__lt=hora_fin,
                        hora_fin__gt=hora_inicio,
                    )
                    .select_related("id_usuario")
                    .first()
                )
                if conflicto:
                    form.add_error(
                        None,
                        f"El vehículo ya tiene una reserva activa para esa franja "
                        f"(#{conflicto.pk}, {conflicto.id_usuario.nombre_completo}). "
                        "Cambiá el vehículo, el horario, o cancelá la otra reserva "
                        "primero.",
                    )
                    return render(
                        request,
                        "reservas/tickets/crear_ticket_manual.html",
                        {"form": form},
                    )

            ticket = Ticket(
                id_usuario=id_usuario,
                id_vehiculo=vehiculo,
                conductor=cd.get("conductor"),
                destino=cd["destino"],
                cant_pasajeros=cd["cant_pasajeros"],
                descripcion=cd.get("descripcion", ""),
                hora_inicio=hora_inicio,
                hora_fin=hora_fin,
                estado=estado,
                kilometraje_inicio=cd.get("kilometraje_inicio"),
                kilometraje_fin=cd.get("kilometraje_fin"),
                requiere_chofer=vehiculo.requiere_chofer or bool(cd.get("conductor")),
            )
            if estado in (Ticket.ESTADO_FINALIZADO, Ticket.ESTADO_CANCELADO):
                ticket._suppress_signals = True
            ticket.save()

            if cd.get("id_usuario"):
                messages.success(
                    request,
                    f"Ticket #{ticket.pk} cargado a nombre de "
                    f"{id_usuario.nombre_completo}.",
                )
            else:
                messages.success(
                    request,
                    f"Ticket #{ticket.pk} cargado a tu nombre (no se especificó "
                    "un usuario solicitante).",
                )
            return redirect("detalle_ticket", ticket_id=ticket.pk)
    else:
        form = TicketManualForm()

    return render(
        request,
        "reservas/tickets/crear_ticket_manual.html",
        {"form": form, "usuario": usuario_admin},
    )
