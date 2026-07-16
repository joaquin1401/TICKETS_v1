"""
Vistas administrativas de supervisión de tickets.

Épica 5 (tickets):
    - HU 5.3: monitor_tickets_activos() — tickets aprobados/en curso.
    - HU 5.4: historial_tickets() — tickets finalizados y cancelados.
    - descargar_historial_csv() — exportación CSV del historial.
"""

import csv
from datetime import date

from django.shortcuts import render
from django.http import HttpResponse
from django.db.models import Q

from ..models import Ticket
from ..forms import FiltroTicketsForm
from ._base import get_usuario_sesion, paginate_queryset, login_requerido, admin_requerido


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
    tickets_qs = Ticket.objects.filter(
        estado__in=[Ticket.ESTADO_APROBADO, Ticket.ESTADO_EN_CURSO],
        hora_inicio__gte=date.today(),
    ).select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo").order_by("-fecha", "-id")

    if form.is_valid():
        from django.db.models.functions import Lower

        busqueda = form.cleaned_data.get("busqueda")
        conductor = form.cleaned_data.get("conductor")
        vehiculo = form.cleaned_data.get("vehiculo")
        cargo = form.cleaned_data.get("cargo")
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
        if cargo:
            tickets_qs = tickets_qs.filter(id_usuario__id_cargo=cargo)
        if fecha_inicio:
            tickets_qs = tickets_qs.filter(hora_inicio__date__gte=fecha_inicio)
        if fecha_fin:
            tickets_qs = tickets_qs.filter(hora_inicio__date__lte=fecha_fin)

    page_obj, pagination_query = paginate_queryset(request, tickets_qs)
    vehiculos_en_uso = tickets_qs.values("id_vehiculo").distinct().count()

    return render(request, "reservas/tickets/tickets_activos.html", {
        "form": form,
        "tickets": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_tickets": page_obj.paginator.count,
        "vehiculos_en_uso": vehiculos_en_uso,
        "usuario": get_usuario_sesion(request),
    })


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
    tickets_qs = Ticket.objects.filter(
        Q(estado__in=[Ticket.ESTADO_CANCELADO, Ticket.ESTADO_FINALIZADO]) | Q(hora_inicio__lt=date.today())
    ).select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo").order_by("-fecha", "-id")

    if form.is_valid():
        from django.db.models.functions import Lower

        busqueda = form.cleaned_data.get("busqueda")
        conductor = form.cleaned_data.get("conductor")
        vehiculo = form.cleaned_data.get("vehiculo")
        cargo = form.cleaned_data.get("cargo")
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
        if cargo:
            tickets_qs = tickets_qs.filter(id_usuario__id_cargo=cargo)
        if fecha_inicio:
            tickets_qs = tickets_qs.filter(hora_inicio__date__gte=fecha_inicio)
        if fecha_fin:
            tickets_qs = tickets_qs.filter(hora_inicio__date__lte=fecha_fin)

    page_obj, pagination_query = paginate_queryset(request, tickets_qs)

    return render(request, "reservas/tickets/historial_tickets.html", {
        "form": form,
        "tickets": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_tickets": page_obj.paginator.count,
        "usuario": get_usuario_sesion(request),
    })


@login_requerido
@admin_requerido
def descargar_historial_csv(request):
    """
    Exporta el historial de tickets a un archivo CSV descargable.
    Aplica los mismos filtros que historial_tickets().
    """
    form = FiltroTicketsForm(request.GET or None)
    tickets_qs = Ticket.objects.filter(
        Q(estado=Ticket.ESTADO_CANCELADO) | Q(hora_inicio__lt=date.today())
    ).select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo").order_by("-fecha", "-id")

    if form.is_valid():
        from django.db.models.functions import Lower

        busqueda = form.cleaned_data.get("busqueda")
        conductor = form.cleaned_data.get("conductor")
        vehiculo = form.cleaned_data.get("vehiculo")
        cargo = form.cleaned_data.get("cargo")
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
        if cargo:
            tickets_qs = tickets_qs.filter(id_usuario__id_cargo=cargo)
        if fecha_inicio:
            tickets_qs = tickets_qs.filter(hora_inicio__date__gte=fecha_inicio)
        if fecha_fin:
            tickets_qs = tickets_qs.filter(hora_inicio__date__lte=fecha_fin)

    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="historial_ticket_{timestamp}.csv"'

    writer = csv.writer(response)
    writer.writerow(['ID', 'Solicitante', 'Cargo', 'Vehiculo', 'Destino', 'Salida', 'Regreso', 'Estado', 'Observacion'])

    from django.utils.timezone import localtime, is_aware
    for t in tickets_qs:
        salida = ""
        if t.hora_inicio:
            dt = localtime(t.hora_inicio) if is_aware(t.hora_inicio) else t.hora_inicio
            salida = dt.strftime("%d/%m/%Y %H:%M")

        regreso = ""
        if t.hora_fin:
            dt = localtime(t.hora_fin) if is_aware(t.hora_fin) else t.hora_fin
            regreso = dt.strftime("%d/%m/%Y %H:%M")

        writer.writerow([
            t.pk,
            t.id_usuario.nombre_completo,
            t.id_usuario.id_cargo.nombre,
            f"{t.id_vehiculo.marca} {t.id_vehiculo.modelo}",
            t.destino,
            salida,
            regreso,
            t.estado,
            t.observacion
        ])

    return response
