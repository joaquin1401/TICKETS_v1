"""
Vistas de analíticas y reportes.

Épica 7:
    - reporte_analiticas() — panel principal de analíticas.
    - analiticas_vehiculo() — analíticas detalladas por vehículo.
    - reporte_analiticas_pdf() — exportación de analíticas a PDF.
"""

from datetime import timedelta
import io

from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from weasyprint import HTML
from django.template.loader import render_to_string

from ..models import Vehiculo, Ticket, Cargo, Usuario
from ..utils.chart_utils import generar_grafico_barras_horizontal, generar_grafico_torta
from ._base import get_usuario_sesion, login_requerido, admin_requerido


# ══════════════════════════════════════════════════════════════════════════════
# ÉPICA 7: ANALÍTICAS Y REPORTES (ADMIN ONLY)
# ══════════════════════════════════════════════════════════════════════════════


@login_requerido
@admin_requerido
def reporte_analiticas(request):
    """
    Vista de analíticas y reportes narrativos de los vehículos (admin only).

    Calcula métricas de uso efectivo por vehículo y globales de la app,
    con filtro de rango temporal. Aplica principios de data storytelling
    (Knaflic & Few): una historia clara, sin ruido, jerarquía intencional.

    Query params:
        rango (str): '30d' | '90d' | 'anio' | 'todo' (default: '30d')

    Métricas por vehículo:
        - Total reservas (aprobadas)
        - Tiempo efectivo de uso (suma horas)
        - Tasa de cancelación

    Métricas globales:
        - Total tickets, usuarios, vehículos
        - Distribución de estados
        - Mes con mayor actividad
        - Vehículo con mayor tasa de cancelación
        - Duración promedio de viaje
        - Usuarios pendientes de aprobación
    """
    usuario = get_usuario_sesion(request)
    rango = request.GET.get("rango", "30d")

    cargo_id = request.GET.get("cargo", "")
    filtro_cargo = None
    if cargo_id:
        try:
            filtro_cargo = Cargo.objects.get(pk=int(cargo_id))
        except (Cargo.DoesNotExist, ValueError):
            filtro_cargo = None

    filtro_departamento = request.GET.get("departamento", "")

    # ── Calcular fecha de corte ──────────────────────────────────────────────
    hoy = timezone.now()
    if rango == "30d":
        desde = hoy - timedelta(days=30)
        rango_label = f"Últimos 30 días ({desde.strftime('%d/%m/%Y')} - {hoy.strftime('%d/%m/%Y')})"
    elif rango == "90d":
        desde = hoy - timedelta(days=90)
        rango_label = f"Últimos 90 días ({desde.strftime('%d/%m/%Y')} - {hoy.strftime('%d/%m/%Y')})"
    elif rango == "anio":
        desde = hoy.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        rango_label = f"Año {hoy.year} ({desde.strftime('%d/%m/%Y')} - {hoy.strftime('%d/%m/%Y')})"
    else:
        desde = None
        rango = "todo"
        rango_label = "Todo el tiempo"

    def filtro_base(qs):
        q = qs.filter(hora_inicio__gte=desde) if desde else qs
        if filtro_cargo:
            q = q.filter(id_usuario__id_cargo=filtro_cargo)
        if filtro_departamento:
            q = q.filter(id_usuario__departamento=filtro_departamento)
        return q

    # ── Tickets en el período ────────────────────────────────────────────────
    tickets_periodo   = filtro_base(Ticket.objects.all())
    tickets_aprobados = tickets_periodo.filter(estado=Ticket.ESTADO_APROBADO)
    tickets_cancelados = tickets_periodo.filter(estado=Ticket.ESTADO_CANCELADO)

    total_tickets            = tickets_periodo.count()
    total_aprobados          = tickets_aprobados.count()
    total_cancelados         = tickets_cancelados.count()
    total_pendientes_tickets = tickets_periodo.filter(estado=Ticket.ESTADO_PENDIENTE).count()

    tasa_cancelacion_global = round(
        (total_cancelados / total_tickets * 100) if total_tickets > 0 else 0, 1
    )

    # ── Métricas por vehículo ────────────────────────────────────────────────
    vehiculos = Vehiculo.objects.all().order_by("marca", "modelo")
    stats_vehiculos = []
    max_horas = 0

    for v in vehiculos:
        t_aprobados  = filtro_base(Ticket.objects.filter(id_vehiculo=v, estado=Ticket.ESTADO_APROBADO))
        t_cancelados = filtro_base(Ticket.objects.filter(id_vehiculo=v, estado=Ticket.ESTADO_CANCELADO))
        t_total      = filtro_base(Ticket.objects.filter(id_vehiculo=v))

        count_aprobados  = t_aprobados.count()
        count_cancelados = t_cancelados.count()
        count_total      = t_total.count()

        tasa_cancel = round(
            (count_cancelados / count_total * 100) if count_total > 0 else 0, 1
        )

        stats_vehiculos.append({
            "vehiculo":         v,
            "count_aprobados":  count_aprobados,
            "count_cancelados": count_cancelados,
            "count_total":      count_total,
            "tasa_cancelacion": tasa_cancel,
        })

    stats_vehiculos.sort(key=lambda x: x["count_aprobados"], reverse=True)

    # ── KPIs de distancia ────────────────────────────────────────────────────
    dist_est_agg  = tickets_periodo.aggregate(total=Sum("distancia_est"))["total"]
    dist_real_agg = tickets_periodo.filter(distancia_real__isnull=False).aggregate(total=Sum("distancia_real"))["total"]
    distancia_est_total  = round(float(dist_est_agg),  1) if dist_est_agg  else 0
    distancia_real_total = round(float(dist_real_agg), 1) if dist_real_agg else 0

    # ── Mes con mayor actividad ──────────────────────────────────────────────
    _MESES_ES = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
        5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
        9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
    }
    mes_pico_label = "—"
    mes_pico_count = 0
    meses_qs = (
        tickets_aprobados
        .annotate(mes=TruncMonth("hora_inicio"))
        .values("mes")
        .annotate(total=Count("id"))
        .order_by("-total")
    )
    if meses_qs.exists():
        top_mes = meses_qs.first()
        mes_dt = top_mes["mes"]
        mes_pico_label = f"{_MESES_ES[mes_dt.month]} {mes_dt.year}"
        mes_pico_count = top_mes["total"]

    # ── Duración promedio de viaje ────────────────────────────────────────────
    duraciones = [
        (t.hora_fin - t.hora_inicio).total_seconds() / 3600
        for t in tickets_aprobados.exclude(hora_fin__isnull=True)
    ]
    duracion_promedio = round(sum(duraciones) / len(duraciones), 1) if duraciones else 0

    # ── Usuarios y vehículos ─────────────────────────────────────────────────────
    total_usuarios_activos    = Usuario.objects.filter(valido=True).count()
    total_usuarios_pendientes = Usuario.objects.filter(valido=False, rechazado=False).count()
    total_vehiculos_activos   = Vehiculo.objects.filter(activo=True).count()
    total_vehiculos_inactivos = Vehiculo.objects.filter(activo=False).count()

    # ── Insights narrativos ───────────────────────────────────────────────────
    insights = []

    if stats_vehiculos and stats_vehiculos[0]["count_aprobados"] > 0:
        lider = stats_vehiculos[0]
        insights.append(
            f"El {lider['vehiculo'].marca} {lider['vehiculo'].modelo} es el vehículo más utilizado "
            f"con {lider['count_aprobados']} reservas aprobadas en {rango_label.lower()}."
        )

    if mes_pico_count > 0:
        insights.append(
            f"{mes_pico_label} fue el mes con mayor demanda: "
            f"{mes_pico_count} reservas aprobadas."
        )

    if duracion_promedio > 0:
        insights.append(
            f"La duración promedio de un viaje es de {duracion_promedio} horas."
        )

    candidatos = [sv for sv in stats_vehiculos if sv["count_total"] >= 3]
    if candidatos:
        peor = max(candidatos, key=lambda x: x["tasa_cancelacion"])
        if peor["tasa_cancelacion"] > tasa_cancelacion_global:
            diff = round(peor["tasa_cancelacion"] - tasa_cancelacion_global, 1)
            insights.append(
                f"El {peor['vehiculo'].marca} {peor['vehiculo'].modelo} tiene una tasa de "
                f"cancelación del {peor['tasa_cancelacion']}%, "
                f"{diff} puntos por encima del promedio de los vehículos."
            )

    if total_usuarios_pendientes > 0:
        insights.append(
            f"Hay {total_usuarios_pendientes} usuario"
            f"{'s' if total_usuarios_pendientes > 1 else ''} "
            f"pendiente{'s' if total_usuarios_pendientes > 1 else ''} de aprobación."
        )

    if not insights:
        insights.append(
            "No hay suficientes datos en el período seleccionado para generar insights."
        )

    # ── Comportamiento de Usuarios ───────────────────────────────────────────

    solicitudes_departamento = tickets_periodo.exclude(id_usuario__departamento__isnull=True).exclude(id_usuario__departamento='').values(
        'id_usuario__departamento'
    ).annotate(
        total=Count('id')
    ).order_by('-total')

    solicitudes_cargo = tickets_periodo.values(
        'id_usuario__id_cargo__nombre'
    ).annotate(
        total=Count('id')
    ).order_by('-total')

    vehiculos_solicitudes = tickets_periodo.values(
        'id_vehiculo__marca', 'id_vehiculo__modelo', 'id_vehiculo__patente'
    ).annotate(
        total=Count('id')
    ).order_by('-total')

    vehiculos_km = tickets_periodo.filter(distancia_real__isnull=False).values(
        'id_vehiculo__marca', 'id_vehiculo__modelo', 'id_vehiculo__patente'
    ).annotate(
        total_km=Sum('distancia_real')
    ).order_by('-total_km')

    # Gráficos con Matplotlib
    l_dept = [u['id_usuario__departamento'] for u in solicitudes_departamento]
    d_dept = [u['total'] for u in solicitudes_departamento]
    chart_departamentos = generar_grafico_barras_horizontal(l_dept, d_dept)

    l_cargos = [c['id_usuario__id_cargo__nombre'] for c in solicitudes_cargo]
    d_cargos = [c['total'] for c in solicitudes_cargo]
    chart_cargos = generar_grafico_torta(l_cargos, d_cargos)

    l_veh_sol = [f"{v['id_vehiculo__marca']} {v['id_vehiculo__modelo']} {v['id_vehiculo__patente']}" for v in vehiculos_solicitudes]
    d_veh_sol = [v['total'] for v in vehiculos_solicitudes]
    chart_vehiculos_sol = generar_grafico_barras_horizontal(l_veh_sol, d_veh_sol)

    l_veh_km = [f"{v['id_vehiculo__marca']} {v['id_vehiculo__modelo']} {v['id_vehiculo__patente']}" for v in vehiculos_km]
    d_veh_km = [float(v['total_km']) for v in vehiculos_km]
    chart_vehiculos_km = generar_grafico_barras_horizontal(l_veh_km, d_veh_km, "{} km")

    cargos_lista = Cargo.objects.all().order_by("prioridad")
    vehiculos_lista = Vehiculo.objects.all().order_by("marca", "modelo")

    return render(request, "reservas/analiticas/analiticas.html", {
        "usuario":                   usuario,
        "rango":                     rango,
        "rango_label":               rango_label,
        "stats_vehiculos":           stats_vehiculos,
        "total_tickets":             total_tickets,
        "total_aprobados":           total_aprobados,
        "total_cancelados":          total_cancelados,
        "total_pendientes_tickets":  total_pendientes_tickets,
        "tasa_cancelacion_global":   tasa_cancelacion_global,
        "distancia_est_total":       distancia_est_total,
        "distancia_real_total":      distancia_real_total,
        "mes_pico_label":            mes_pico_label,
        "mes_pico_count":            mes_pico_count,
        "duracion_promedio":         duracion_promedio,
        "total_usuarios_activos":    total_usuarios_activos,
        "total_usuarios_pendientes": total_usuarios_pendientes,
        "total_vehiculos_activos":   total_vehiculos_activos,
        "total_vehiculos_inactivos": total_vehiculos_inactivos,
        "insights":                  insights,
        "solicitudes_departamento":  solicitudes_departamento,
        "solicitudes_cargo":         solicitudes_cargo,
        "chart_departamentos":       chart_departamentos,
        "chart_cargos":              chart_cargos,
        "chart_vehiculos_sol":       chart_vehiculos_sol,
        "chart_vehiculos_km":        chart_vehiculos_km,
        "cargos_lista":              cargos_lista,
        "vehiculos_lista":           vehiculos_lista,
        "filtro_cargo":              filtro_cargo,
        "filtro_departamento":       filtro_departamento,
        "cargo_id":                  cargo_id,
        "departamentos_lista":       Usuario.DEPARTAMENTOS_CHOICES,
    })


@login_requerido
@admin_requerido
def analiticas_vehiculo(request, vehiculo_id):
    """
    Vista de analíticas detalladas para un vehículo específico.
    Muestra KPIs individuales, detalles del vehículo y permite filtrar por rango temporal.
    """
    usuario = get_usuario_sesion(request)
    vehiculo = get_object_or_404(Vehiculo, pk=vehiculo_id)
    rango = request.GET.get("rango", "30d")

    _MESES_ES = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
        5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
        9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
    }

    hoy = timezone.now()
    if rango == "30d":
        desde = hoy - timedelta(days=30)
        rango_label = f"Últimos 30 días ({desde.strftime('%d/%m/%Y')} - {hoy.strftime('%d/%m/%Y')})"
    elif rango == "90d":
        desde = hoy - timedelta(days=90)
        rango_label = f"Últimos 90 días ({desde.strftime('%d/%m/%Y')} - {hoy.strftime('%d/%m/%Y')})"
    elif rango == "anio":
        desde = hoy.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        rango_label = f"Año {hoy.year} ({desde.strftime('%d/%m/%Y')} - {hoy.strftime('%d/%m/%Y')})"
    else:
        desde = None
        rango = "todo"
        rango_label = "Todo el tiempo"

    base_qs = Ticket.objects.filter(id_vehiculo=vehiculo)
    if desde:
        base_qs = base_qs.filter(hora_inicio__gte=desde)

    tickets_aprobados  = base_qs.filter(estado__in=[Ticket.ESTADO_APROBADO, Ticket.ESTADO_EN_CURSO, Ticket.ESTADO_FINALIZADO])
    tickets_cancelados = base_qs.filter(estado=Ticket.ESTADO_CANCELADO)
    count_total        = base_qs.count()
    count_aprobados    = tickets_aprobados.count()
    count_cancelados   = tickets_cancelados.count()

    # Distancias
    dist_est_agg  = base_qs.aggregate(total=Sum("distancia_est"))["total"]
    dist_real_agg = base_qs.filter(distancia_real__isnull=False).aggregate(total=Sum("distancia_real"))["total"]
    distancia_est_total  = round(float(dist_est_agg),  1) if dist_est_agg  else 0
    distancia_real_total = round(float(dist_real_agg), 1) if dist_real_agg else 0

    # Duración promedio
    duraciones = [
        (t.hora_fin - t.hora_inicio).total_seconds() / 3600
        for t in tickets_aprobados.exclude(hora_fin__isnull=True)
    ]
    duracion_promedio = round(sum(duraciones) / len(duraciones), 1) if duraciones else 0

    # Último kilometraje_fin registrado
    ultimo_ticket_km = (
        Ticket.objects.filter(id_vehiculo=vehiculo, kilometraje_fin__isnull=False)
        .order_by("-hora_fin_real", "-hora_fin", "-fecha")
        .first()
    )
    ultimo_km_fin    = ultimo_ticket_km.kilometraje_fin if ultimo_ticket_km else None
    ultima_fecha_km  = None
    if ultimo_ticket_km:
        dt = ultimo_ticket_km.hora_fin_real or ultimo_ticket_km.hora_fin or ultimo_ticket_km.fecha
        if dt:
            from django.utils.timezone import localtime, is_aware
            dt = localtime(dt) if is_aware(dt) else dt
            ultima_fecha_km = dt.strftime("%d/%m/%Y")

    # Tasa de cancelación
    tasa_cancelacion = round(
        (count_cancelados / count_total * 100) if count_total > 0 else 0, 1
    )

    # Top usuarios de este vehículo
    top_usuarios_veh = (
        base_qs.values("id_usuario__nombre", "id_usuario__apellido", "id_usuario__id_cargo__nombre")
        .annotate(total=Count("id"))
        .order_by("-total")[:5]
    )

    vehiculos_lista = Vehiculo.objects.all().order_by("marca", "modelo")

    return render(request, "reservas/analiticas/analiticas_vehiculo.html", {
        "usuario":             usuario,
        "vehiculo":            vehiculo,
        "rango":               rango,
        "rango_label":         rango_label,
        "count_total":         count_total,
        "count_aprobados":     count_aprobados,
        "count_cancelados":    count_cancelados,
        "distancia_est_total": distancia_est_total,
        "distancia_real_total":distancia_real_total,
        "duracion_promedio":   duracion_promedio,
        "tasa_cancelacion":    tasa_cancelacion,
        "ultimo_km_fin":       ultimo_km_fin,
        "ultima_fecha_km":     ultima_fecha_km,
        "top_usuarios_veh":    top_usuarios_veh,
        "vehiculos_lista":     vehiculos_lista,
    })


@login_requerido
@admin_requerido
def reporte_analiticas_pdf(request):
    """
    Genera y descarga el reporte de analíticas como PDF usando WeasyPrint.

    Reutiliza la misma lógica de cálculo de reporte_analiticas() y renderiza
    un template standalone (sin sidebar/nav) optimizado para WeasyPrint.

    Query params:
        rango (str): '30d' | '90d' | 'anio' | 'todo'
    """
    usuario = get_usuario_sesion(request)
    rango = request.GET.get("rango", "30d")

    # ── Filtro por cargo/departamento ────────────────────────────────────────
    cargo_id = request.GET.get("cargo", "")
    filtro_cargo = None
    if cargo_id:
        try:
            filtro_cargo = Cargo.objects.get(pk=int(cargo_id))
        except (Cargo.DoesNotExist, ValueError):
            filtro_cargo = None

    filtro_departamento = request.GET.get("departamento", "")

    hoy = timezone.now()
    if rango == "30d":
        desde = hoy - timedelta(days=30)
        rango_label = f"Últimos 30 días ({desde.strftime('%d/%m/%Y')} - {hoy.strftime('%d/%m/%Y')})"
    elif rango == "90d":
        desde = hoy - timedelta(days=90)
        rango_label = f"Últimos 90 días ({desde.strftime('%d/%m/%Y')} - {hoy.strftime('%d/%m/%Y')})"
    elif rango == "anio":
        desde = hoy.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        rango_label = f"Año {hoy.year} ({desde.strftime('%d/%m/%Y')} - {hoy.strftime('%d/%m/%Y')})"
    else:
        desde = None
        rango = "todo"
        rango_label = "Todo el tiempo"

    def filtro_base(qs):
        q = qs.filter(hora_inicio__gte=desde) if desde else qs
        if filtro_cargo:
            q = q.filter(id_usuario__id_cargo=filtro_cargo)
        if filtro_departamento:
            q = q.filter(id_usuario__departamento=filtro_departamento)
        return q

    tickets_periodo    = filtro_base(Ticket.objects.all())
    tickets_aprobados  = tickets_periodo.filter(estado=Ticket.ESTADO_APROBADO)
    tickets_cancelados = tickets_periodo.filter(estado=Ticket.ESTADO_CANCELADO)

    total_tickets            = tickets_periodo.count()
    total_aprobados          = tickets_aprobados.count()
    total_cancelados         = tickets_cancelados.count()
    total_pendientes_tickets = tickets_periodo.filter(estado=Ticket.ESTADO_PENDIENTE).count()
    tasa_cancelacion_global  = round(
        (total_cancelados / total_tickets * 100) if total_tickets > 0 else 0, 1
    )

    vehiculos = Vehiculo.objects.all().order_by("marca", "modelo")
    stats_vehiculos = []
    max_horas = 0

    for v in vehiculos:
        t_aprobados  = filtro_base(Ticket.objects.filter(id_vehiculo=v, estado=Ticket.ESTADO_APROBADO))
        t_cancelados = filtro_base(Ticket.objects.filter(id_vehiculo=v, estado=Ticket.ESTADO_CANCELADO))
        t_total      = filtro_base(Ticket.objects.filter(id_vehiculo=v))
        count_aprobados  = t_aprobados.count()
        count_cancelados = t_cancelados.count()
        count_total      = t_total.count()
        stats_vehiculos.append({
            "vehiculo":         v,
            "count_aprobados":  count_aprobados,
            "count_cancelados": count_cancelados,
            "count_total":      count_total,
            "tasa_cancelacion": round((count_cancelados / count_total * 100) if count_total > 0 else 0, 1),
        })

    stats_vehiculos.sort(key=lambda x: x["count_aprobados"], reverse=True)

    _MESES_ES = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
        5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
        9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
    }
    mes_pico_label = "—"
    mes_pico_count = 0
    meses_qs = (
        tickets_aprobados
        .annotate(mes=TruncMonth("hora_inicio"))
        .values("mes")
        .annotate(total=Count("id"))
        .order_by("-total")
    )
    if meses_qs.exists():
        top_mes = meses_qs.first()
        mes_pico_label = f"{_MESES_ES[top_mes['mes'].month]} {top_mes['mes'].year}"
        mes_pico_count = top_mes["total"]

    duraciones = [
        (t.hora_fin - t.hora_inicio).total_seconds() / 3600
        for t in tickets_aprobados.exclude(hora_fin__isnull=True)
    ]
    duracion_promedio = round(sum(duraciones) / len(duraciones), 1) if duraciones else 0

    # ── Comportamiento de Usuarios ───────────────────────────────────────────
    solicitudes_departamento = tickets_periodo.exclude(id_usuario__departamento__isnull=True).exclude(id_usuario__departamento='').values(
        'id_usuario__departamento'
    ).annotate(
        total=Count('id')
    ).order_by('-total')

    solicitudes_cargo = tickets_periodo.values(
        'id_usuario__id_cargo__nombre'
    ).annotate(
        total=Count('id')
    ).order_by('-total')

    vehiculos_solicitudes = tickets_periodo.values(
        'id_vehiculo__marca', 'id_vehiculo__modelo', 'id_vehiculo__patente'
    ).annotate(
        total=Count('id')
    ).order_by('-total')

    vehiculos_km = tickets_periodo.filter(distancia_real__isnull=False).values(
        'id_vehiculo__marca', 'id_vehiculo__modelo', 'id_vehiculo__patente'
    ).annotate(
        total_km=Sum('distancia_real')
    ).order_by('-total_km')

    # Gráficos con Matplotlib
    l_dept = [u['id_usuario__departamento'] for u in solicitudes_departamento]
    d_dept = [u['total'] for u in solicitudes_departamento]
    chart_departamentos = generar_grafico_barras_horizontal(l_dept, d_dept)

    l_cargos = [c['id_usuario__id_cargo__nombre'] for c in solicitudes_cargo]
    d_cargos = [c['total'] for c in solicitudes_cargo]
    chart_cargos = generar_grafico_torta(l_cargos, d_cargos)

    l_veh_sol = [f"{v['id_vehiculo__marca']} {v['id_vehiculo__modelo']} {v['id_vehiculo__patente']}" for v in vehiculos_solicitudes]
    d_veh_sol = [v['total'] for v in vehiculos_solicitudes]
    chart_vehiculos_sol = generar_grafico_barras_horizontal(l_veh_sol, d_veh_sol)

    l_veh_km = [f"{v['id_vehiculo__marca']} {v['id_vehiculo__modelo']} {v['id_vehiculo__patente']}" for v in vehiculos_km]
    d_veh_km = [float(v['total_km']) for v in vehiculos_km]
    chart_vehiculos_km = generar_grafico_barras_horizontal(l_veh_km, d_veh_km, "{} km")

    dist_est_agg  = tickets_periodo.aggregate(total=Sum("distancia_est"))["total"]
    dist_real_agg = tickets_periodo.filter(distancia_real__isnull=False).aggregate(total=Sum("distancia_real"))["total"]
    distancia_est_total  = round(float(dist_est_agg),  1) if dist_est_agg  else 0
    distancia_real_total = round(float(dist_real_agg), 1) if dist_real_agg else 0

    context = {
        "usuario":                   usuario,
        "rango":                     rango,
        "rango_label":               rango_label,
        "stats_vehiculos":           stats_vehiculos,
        "total_tickets":             total_tickets,
        "total_aprobados":           total_aprobados,
        "total_cancelados":          total_cancelados,
        "total_pendientes_tickets":  total_pendientes_tickets,
        "tasa_cancelacion_global":   tasa_cancelacion_global,
        "distancia_est_total":       distancia_est_total,
        "distancia_real_total":      distancia_real_total,
        "mes_pico_label":            mes_pico_label,
        "mes_pico_count":            mes_pico_count,
        "duracion_promedio":         duracion_promedio,
        "total_usuarios_activos":    Usuario.objects.filter(valido=True).count(),
        "total_usuarios_pendientes": Usuario.objects.filter(valido=False, rechazado=False).count(),
        "total_vehiculos_activos":   Vehiculo.objects.filter(activo=True).count(),
        "total_vehiculos_inactivos": Vehiculo.objects.filter(activo=False).count(),
        "fecha_generacion":          f"{hoy.day} de {_MESES_ES[hoy.month]} de {hoy.year}",
        "solicitudes_departamento":  solicitudes_departamento,
        "solicitudes_cargo":         solicitudes_cargo,
        "chart_departamentos":       chart_departamentos,
        "chart_cargos":              chart_cargos,
        "chart_vehiculos_sol":       chart_vehiculos_sol,
        "chart_vehiculos_km":        chart_vehiculos_km,
        "filtro_cargo":              filtro_cargo,
        "filtro_departamento":       filtro_departamento,
    }

    html_string = render_to_string("reservas/analiticas/analiticas_pdf.html", context)
    pdf_bytes = HTML(string=html_string).write_pdf()

    filename = f"analiticas_{rango}_{hoy.strftime('%Y%m%d')}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
