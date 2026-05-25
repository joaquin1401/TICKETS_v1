"""
views_refactored_example.py - Ejemplo de vista refactorizada con arquitectura limpia.

⚠️ EJEMPLO EDUCATIVO
───────────────────
Este archivo muestra cómo refactorizar las vistas existentes usando la nueva
arquitectura (managers, selectors, decorators, middleware).

NO EJECUTAR DIRECTAMENTE - Hacer copy-paste selectivo en views.py real.

Cambios principales:
✓ Usa request.user (inyectado por middleware) en lugar de get_usuario_sesion()
✓ Usa selectors.* para consultas
✓ Usa decorators.* para validaciones
✓ Usa managers para QuerySets
✓ Mejor manejo de errores
✓ Type hints para claridad

Pasos para migrar:
1. Instalar middleware en settings.py
2. Migrar vistas una por una (no todo de golpe)
3. Ir eliminando funciones redundantes del código viejo
4. Actualizar tests progresivamente
"""

from datetime import datetime, date, timedelta
from typing import Optional
import calendar

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpRequest, HttpResponse

from .models import Usuario, Vehiculo, Ticket, Cargo
from .forms import (
    RegistroForm, LoginForm, TicketForm, VehiculoSelectorForm,
    FiltroUsuariosForm, VehiculoForm,
)
from .services import crear_ticket_con_reglas, ResultadoCreacion
from . import selectors
from .decorators import login_requerido, admin_requerido, requiere_usuario_activo
from .utils import formatear_duracion


# ════════════════════════════════════════════════════════════════════════════
# ÉPICA 2: Dashboard y Tickets del Usuario
# ════════════════════════════════════════════════════════════════════════════

@login_requerido
@requiere_usuario_activo
def dashboard_refactorizado(request: HttpRequest) -> HttpResponse:
    """
    HU 2.1 — Dashboard con formulario de reserva rápida (REFACTORIZADO).
    
    Cambios vs versión anterior:
    ✓ request.user viene de middleware (no get_usuario_sesion)
    ✓ Usa selectors.get_tickets_usuario() en lugar de query duplicada
    ✓ request.es_admin también viene de middleware
    ✓ Better error handling con message tags
    ✓ Type hints en función
    
    Flujo:
    1. GET → Muestra form + últimos 5 tickets del usuario
    2. POST → Valida form, llama a servicio de creación, muestra resultado
    """
    usuario = request.user  # Inyectado por middleware ✓
    form = TicketForm()

    if request.method == "POST":
        form = TicketForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            
            # Determinar hora_fin (si no se especifica, +2 horas por defecto)
            hora_fin = cd.get("hora_fin") or (cd["hora_inicio"] + timedelta(hours=2))

            # Llamar al servicio de negocio
            # Nota: Esta lógica de creación con reglas está en services.py (transaction.atomic)
            resultado = crear_ticket_con_reglas(
                usuario=usuario,
                vehiculo=cd["id_vehiculo"],
                hora_inicio=cd["hora_inicio"],
                hora_fin=hora_fin,
                destino=cd["destino"],
                cant_pasajeros=cd["cant_pasajeros"],
                descripcion=cd.get("descripcion", ""),
            )

            # Mostrar resultado al usuario
            if resultado.exito:
                if resultado.estado == ResultadoCreacion.SOBRESCRITO:
                    # Sobrescritura exitosa por mayor jerarquía
                    messages.warning(request, resultado.mensaje, extra_tags="warning")
                else:
                    # Creación normal exitosa
                    messages.success(request, resultado.mensaje)
                return redirect("historial")
            else:
                # Fallo: ticket bloqueado por conflicto de menor jerarquía
                messages.error(request, resultado.mensaje)
                # No redirige, muestra form de nuevo con error

    # Obtener últimos 5 tickets del usuario (optimizado con select_related)
    # Nota: selectors.get_tickets_usuario() ya trae select_related aplicado
    tickets_recientes = selectors.get_tickets_usuario(usuario)[:5]

    return render(request, "reservas/dashboard.html", {
        "form": form,
        "usuario": usuario,
        "tickets_recientes": tickets_recientes,
        "es_admin": request.es_admin,  # Disponible por middleware
    })


@login_requerido
@requiere_usuario_activo
def historial_refactorizado(request: HttpRequest) -> HttpResponse:
    """
    HU 2.2 — Historial de tickets del usuario (REFACTORIZADO).
    
    Cambios:
    ✓ Usa selectors.get_tickets_usuario() centralizado
    ✓ request.user viene del middleware
    ✓ Más simple y mantenible
    
    Nota: En futuro, agregar paginación aquí si hay muchos tickets.
    """
    usuario = request.user
    
    # Query optimizada con select_related en selector
    tickets = selectors.get_tickets_usuario(usuario)
    
    return render(request, "reservas/historial.html", {
        "tickets": tickets,
        "usuario": usuario,
    })


@login_requerido
@requiere_usuario_activo
def detalle_ticket_refactorizado(request: HttpRequest, ticket_id: int) -> HttpResponse:
    """
    HU 2.3 — Detalle de un ticket específico (REFACTORIZADO).
    
    Cambios:
    ✓ Mejor validación: User normal solo ve sus tickets, admin ve todos
    ✓ Usa request.es_admin en lugar de session check
    ✓ Decorador @requiere_usuario_activo garantiza usuario válido
    """
    usuario = request.user
    
    # Admin puede ver cualquier ticket; usuario normal solo los suyos
    if request.es_admin:
        ticket = get_object_or_404(Ticket, pk=ticket_id)
    else:
        ticket = get_object_or_404(Ticket, pk=ticket_id, id_usuario=usuario)

    # Calcular información adicional para mostrar
    puede_cancelar = ticket.puede_ser_cancelado()
    esta_en_progreso = ticket.esta_en_progreso()
    duracion = formatear_duracion(ticket.hora_inicio, ticket.hora_fin)

    return render(request, "reservas/detalle_ticket.html", {
        "ticket": ticket,
        "usuario": usuario,
        "puede_cancelar": puede_cancelar,
        "esta_en_progreso": esta_en_progreso,
        "duracion": duracion,
    })


# ════════════════════════════════════════════════════════════════════════════
# ÉPICA 5: Gestión Administrativa
# ════════════════════════════════════════════════════════════════════════════

@login_requerido
@admin_requerido
def directorio_usuarios_refactorizado(request: HttpRequest) -> HttpResponse:
    """
    HU 5.1 — Directorio de usuarios con búsqueda (REFACTORIZADO).
    
    Cambios:
    ✓ Usa selectors.buscar_usuarios() en lugar de query en vista
    ✓ request.es_admin validado por decorador
    ✓ Mejor separación: lógica de búsqueda en selectors.py
    
    Ventaja de arquitectura: Si queremos cambiar la búsqueda,
                            editamos selectors.py, no 5 vistas diferentes.
    """
    form = FiltroUsuariosForm(request.GET or None)
    usuarios = selectors.Usuario.objects.activos()  # Base: solo usuarios válidos

    if form.is_valid():
        busqueda = form.cleaned_data.get("busqueda")
        cargo = form.cleaned_data.get("cargo")
        
        # Uso de selector reutilizable
        usuarios = selectors.buscar_usuarios(busqueda=busqueda, cargo=cargo)

    return render(request, "reservas/directorio_usuarios.html", {
        "form": form,
        "usuarios": usuarios,
        "usuario": request.user,
    })


@login_requerido
@admin_requerido
def monitor_tickets_activos_refactorizado(request: HttpRequest) -> HttpResponse:
    """
    HU 5.3 — Monitor de tickets activos (REFACTORIZADO).
    
    Cambios:
    ✓ Usa selectors.get_tickets_activos_empresa()
    ✓ Query con select_related predefinido = sin N+1
    ✓ Decoradores validan permisos automáticamente
    
    Performance note: get_tickets_activos_empresa() optimiza con select_related.
                      Sin esto, acceder a usuario/vehículo en template = N queries.
    """
    # Selector maneja query optimizada
    tickets = selectors.get_tickets_activos_empresa()

    return render(request, "reservas/monitor_activos.html", {
        "tickets": tickets,
        "usuario": request.user,
    })


# ════════════════════════════════════════════════════════════════════════════
# ÉPICA 3: Calendario Interactivo
# ════════════════════════════════════════════════════════════════════════════

@login_requerido
@requiere_usuario_activo
def calendario_refactorizado(request: HttpRequest) -> HttpResponse:
    """
    HU 3.1 / 3.2 — Selector de vehículo + vista mensual (REFACTORIZADO).
    
    Cambios:
    ✓ Usa selectors.get_dias_con_reservas() para obtener días ocupados
    ✓ request.es_admin disponible para mostrar/ocultar opciones
    ✓ Mejor separación: lógica de "qué días tienen reservas" está en selectors
    
    Nota: Si hay muchos vehículos, consideraría agregar paginación al form.
    """
    usuario = request.user
    form = VehiculoSelectorForm(request.GET or None)

    vehiculo = None
    dias_con_reservas = set()
    
    # Obtener mes/año de parámetros o usar actual
    anio = int(request.GET.get("anio", date.today().year))
    mes = int(request.GET.get("mes", date.today().month))

    if form.is_valid():
        vehiculo = form.cleaned_data["vehiculo"]
        
        # Selector reutilizable: obtener días con reservas
        dias_con_reservas = selectors.get_dias_con_reservas(vehiculo, anio, mes)

    # Generar calendario HTML
    cal = calendar.monthcalendar(anio, mes)
    nombre_mes = date(anio, mes, 1).strftime("%B %Y").capitalize()

    # Calcular navegación
    if mes == 1:
        mes_anterior = (anio - 1, 12)
    else:
        mes_anterior = (anio, mes - 1)
    
    if mes == 12:
        mes_siguiente = (anio + 1, 1)
    else:
        mes_siguiente = (anio, mes + 1)

    return render(request, "reservas/calendario.html", {
        "form": form,
        "vehiculo": vehiculo,
        "cal": cal,
        "nombre_mes": nombre_mes,
        "anio": anio,
        "mes": mes,
        "dias_con_reservas": dias_con_reservas,
        "mes_anterior": mes_anterior,
        "mes_siguiente": mes_siguiente,
        "usuario": usuario,
    })


@login_requerido
@requiere_usuario_activo
def timeline_dia_refactorizado(request: HttpRequest, vehiculo_id: int, anio: int, mes: int, dia: int) -> HttpResponse:
    """
    HU 3.3 — Timeline horaria de un día (REFACTORIZADO).
    
    Cambios:
    ✓ Usa selectors.get_tickets_aprobados_dia()
    ✓ Manejo mejorado de errores (get_object_or_404)
    ✓ request.user directamente disponible
    """
    usuario = request.user
    
    try:
        fecha = date(anio, mes, dia)
    except ValueError:
        # Fecha inválida
        messages.error(request, "Fecha inválida.")
        return redirect("calendario")

    # Verificar que vehículo existe y está activo
    vehiculo = get_object_or_404(Vehiculo, pk=vehiculo_id, activo=True)
    
    # Obtener tickets del día (selector optimizado)
    tickets = selectors.get_tickets_aprobados_dia(vehiculo, fecha)

    return render(request, "reservas/timeline_dia.html", {
        "vehiculo": vehiculo,
        "fecha": fecha,
        "tickets": tickets,
        "usuario": usuario,
    })
