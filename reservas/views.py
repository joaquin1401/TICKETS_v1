"""
views.py — Vistas tradicionales (templates) para todas las épicas.

Convención de sesión:
    request.session["usuario_id"]   → PK del usuario logueado
    request.session["es_admin"]     → bool
"""

import calendar
from datetime import date, timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q

from .models import Usuario, Vehiculo, Ticket, Cargo
from .forms import (
    RegistroForm, LoginForm, TicketForm, VehiculoSelectorForm,
    FiltroUsuariosForm, VehiculoForm,
)
from .services import (
    crear_ticket_con_reglas, ResultadoCreacion,
    get_tickets_del_mes, get_tickets_del_dia,
)


# ══════════════════════════════════════════════
# Helpers / decoradores simples
# ══════════════════════════════════════════════

def get_usuario_sesion(request):
    uid = request.session.get("usuario_id")
    if not uid:
        return None
    try:
        return Usuario.objects.select_related("id_cargo").get(pk=uid)
    except Usuario.DoesNotExist:
        return None


def login_requerido(view_func):
    """Redirige al login si no hay sesión activa."""
    def wrapper(request, *args, **kwargs):
        if not request.session.get("usuario_id"):
            return redirect("login")
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


def admin_requerido(view_func):
    """Redirige si el usuario no es administrador."""
    def wrapper(request, *args, **kwargs):
        if not request.session.get("es_admin"):
            messages.error(request, "No tenés permisos para acceder a esa sección.")
            return redirect("dashboard")
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


# ══════════════════════════════════════════════
# Épica 1 — Autenticación
# ══════════════════════════════════════════════

def registro(request):
    """HU 1.1 — Registro de cuenta."""
    if request.method == "POST":
        form = RegistroForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                "Tu cuenta fue creada. Un administrador deberá aprobar tu acceso antes de que puedas ingresar.",
            )
            return redirect("login")
    else:
        form = RegistroForm()
    return render(request, "reservas/registro.html", {"form": form})


def login_view(request):
    """HU 1.2 — Inicio de sesión."""
    if request.session.get("usuario_id"):
        return redirect("dashboard")

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            correo = form.cleaned_data["correo"]
            contrasena = form.cleaned_data["contrasena"]
            try:
                usuario = Usuario.objects.select_related("id_cargo").get(correo=correo)
            except Usuario.DoesNotExist:
                messages.error(request, "Correo o contraseña incorrectos.")
                return render(request, "reservas/login.html", {"form": form})

            if not usuario.check_password(contrasena):
                messages.error(request, "Correo o contraseña incorrectos.")
                return render(request, "reservas/login.html", {"form": form})

            if usuario.rechazado:
                messages.error(request, "Tu solicitud de acceso fue rechazada. Contactá al administrador.")
                return render(request, "reservas/login.html", {"form": form})

            if not usuario.valido:
                messages.warning(request, "Tu cuenta está pendiente de aprobación por un administrador.")
                return render(request, "reservas/login.html", {"form": form})

            # Sesión — se distingue admin por cargo con prioridad 0 o flag
            request.session["usuario_id"] = usuario.pk
            request.session["es_admin"] = (usuario.id_cargo.nombre.lower() == "administrador")
            return redirect("dashboard")
    else:
        form = LoginForm()
    return render(request, "reservas/login.html", {"form": form})


def logout_view(request):
    request.session.flush()
    return redirect("login")


# ══════════════════════════════════════════════
# Épica 2 — Dashboard y tickets (usuario normal)
# ══════════════════════════════════════════════

@login_requerido
def dashboard(request):
    """HU 2.1 — Dashboard con formulario de reserva rápida."""
    usuario = get_usuario_sesion(request)
    form = TicketForm()

    if request.method == "POST":
        form = TicketForm(request.POST)
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
            )

            if resultado.exito:
                if resultado.estado == ResultadoCreacion.SOBRESCRITO:
                    messages.warning(request, resultado.mensaje)
                else:
                    messages.success(request, resultado.mensaje)
                return redirect("historial")
            else:
                messages.error(request, resultado.mensaje)

    tickets_recientes = Ticket.objects.filter(
        id_usuario=usuario
    ).select_related("id_vehiculo").order_by("-hora_inicio")[:5]

    return render(request, "reservas/dashboard.html", {
        "form": form,
        "usuario": usuario,
        "tickets_recientes": tickets_recientes,
    })


@login_requerido
def historial(request):
    """HU 2.2 — Historial de tickets del usuario."""
    usuario = get_usuario_sesion(request)
    tickets = Ticket.objects.filter(
        id_usuario=usuario
    ).select_related("id_vehiculo").order_by("-hora_inicio")
    return render(request, "reservas/historial.html", {
        "tickets": tickets,
        "usuario": usuario,
    })


@login_requerido
def detalle_ticket(request, ticket_id):
    """HU 2.3 — Detalle de un ticket específico."""
    usuario = get_usuario_sesion(request)
    # Admin puede ver cualquier ticket; usuario solo los suyos
    if request.session.get("es_admin"):
        ticket = get_object_or_404(Ticket, pk=ticket_id)
    else:
        ticket = get_object_or_404(Ticket, pk=ticket_id, id_usuario=usuario)

    return render(request, "reservas/detalle_ticket.html", {
        "ticket": ticket,
        "usuario": usuario,
    })


# ══════════════════════════════════════════════
# Épica 3 — Calendario interactivo
# ══════════════════════════════════════════════

@login_requerido
def calendario(request):
    """HU 3.1 / 3.2 — Selector de vehículo + vista mensual."""
    usuario = get_usuario_sesion(request)
    form = VehiculoSelectorForm(request.GET or None)

    vehiculo = None
    dias_con_reservas = set()
    anio = int(request.GET.get("anio", date.today().year))
    mes = int(request.GET.get("mes", date.today().month))

    if form.is_valid():
        vehiculo = form.cleaned_data["vehiculo"]
        tickets_mes = get_tickets_del_mes(vehiculo, anio, mes)
        dias_con_reservas = {t.hora_inicio.date() for t in tickets_mes}

    cal = calendar.monthcalendar(anio, mes)
    nombre_mes = date(anio, mes, 1).strftime("%B %Y").capitalize()

    # Navegación mes anterior / siguiente
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
def timeline_dia(request, vehiculo_id, anio, mes, dia):
    """HU 3.3 — Línea de tiempo horaria de un día específico."""
    usuario = get_usuario_sesion(request)
    vehiculo = get_object_or_404(Vehiculo, pk=vehiculo_id, activo=True)
    fecha = date(anio, mes, dia)
    tickets = get_tickets_del_dia(vehiculo, fecha)
    return render(request, "reservas/timeline_dia.html", {
        "vehiculo": vehiculo,
        "fecha": fecha,
        "tickets": tickets,
        "usuario": usuario,
    })


# ══════════════════════════════════════════════
# Épica 5 — Gestión y supervisión administrativa
# ══════════════════════════════════════════════

@login_requerido
@admin_requerido
def panel_validacion(request):
    """HU 1.3 / 1.4 — Panel de usuarios pendientes + aprobación/rechazo."""
    pendientes = Usuario.objects.filter(valido=False, rechazado=False).select_related("id_cargo")

    if request.method == "POST":
        uid = request.POST.get("usuario_id")
        accion = request.POST.get("accion")
        usuario_objetivo = get_object_or_404(Usuario, pk=uid)

        if accion == "aprobar":
            usuario_objetivo.valido = True
            usuario_objetivo.rechazado = False
            usuario_objetivo.save(update_fields=["valido", "rechazado"])
            messages.success(request, f"{usuario_objetivo.nombre_completo} fue aprobado.")
        elif accion == "rechazar":
            usuario_objetivo.valido = False
            usuario_objetivo.rechazado = True
            usuario_objetivo.save(update_fields=["valido", "rechazado"])
            messages.warning(request, f"{usuario_objetivo.nombre_completo} fue rechazado.")

        return redirect("panel_validacion")

    return render(request, "reservas/panel_validacion.html", {
        "pendientes": pendientes,
        "usuario": get_usuario_sesion(request),
    })


@login_requerido
@admin_requerido
def directorio_usuarios(request):
    """HU 5.1 — Directorio con búsqueda y filtros."""
    form = FiltroUsuariosForm(request.GET or None)
    usuarios = Usuario.objects.filter(valido=True).select_related("id_cargo")

    if form.is_valid():
        busqueda = form.cleaned_data.get("busqueda")
        cargo = form.cleaned_data.get("cargo")
        if busqueda:
            usuarios = usuarios.filter(
                Q(nombre__icontains=busqueda)
                | Q(apellido__icontains=busqueda)
                | Q(correo__icontains=busqueda)
            )
        if cargo:
            usuarios = usuarios.filter(id_cargo=cargo)

    return render(request, "reservas/directorio_usuarios.html", {
        "form": form,
        "usuarios": usuarios,
        "usuario": get_usuario_sesion(request),
    })


@login_requerido
@admin_requerido
def usuarios_rechazados(request):
    """HU 5.2 — Vista de usuarios rechazados."""
    rechazados = Usuario.objects.filter(rechazado=True).select_related("id_cargo")
    return render(request, "reservas/usuarios_rechazados.html", {
        "rechazados": rechazados,
        "usuario": get_usuario_sesion(request),
    })


@login_requerido
@admin_requerido
def monitor_tickets_activos(request):
    """HU 5.3 — Monitor de tickets activos de toda la empresa."""
    tickets = Ticket.objects.filter(
        estado=Ticket.ESTADO_APROBADO,
        hora_inicio__gte=date.today(),
    ).select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo").order_by("hora_inicio")

    return render(request, "reservas/monitor_activos.html", {
        "tickets": tickets,
        "usuario": get_usuario_sesion(request),
    })


@login_requerido
@admin_requerido
def auditoria_tickets(request):
    """HU 5.4 — Auditoría de tickets históricos y cancelados."""
    tickets = Ticket.objects.filter(
        Q(estado=Ticket.ESTADO_CANCELADO) | Q(hora_inicio__lt=date.today())
    ).select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo").order_by("-hora_inicio")

    return render(request, "reservas/auditoria.html", {
        "tickets": tickets,
        "usuario": get_usuario_sesion(request),
    })


# ══════════════════════════════════════════════
# Épica 6 — ABM de Flota
# ══════════════════════════════════════════════

@login_requerido
@admin_requerido
def listado_flota(request):
    """HU 6.1 — Listado de todos los vehículos."""
    vehiculos = Vehiculo.objects.all().order_by("marca", "modelo")
    return render(request, "reservas/listado_flota.html", {
        "vehiculos": vehiculos,
        "usuario": get_usuario_sesion(request),
    })


@login_requerido
@admin_requerido
def alta_vehiculo(request):
    """HU 6.2 — Alta de vehículo."""
    if request.method == "POST":
        form = VehiculoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Vehículo agregado a la flota.")
            return redirect("listado_flota")
    else:
        form = VehiculoForm()
    return render(request, "reservas/form_vehiculo.html", {
        "form": form,
        "titulo": "Agregar vehículo",
        "usuario": get_usuario_sesion(request),
    })


@login_requerido
@admin_requerido
def edicion_vehiculo(request, vehiculo_id):
    """HU 6.3 — Edición / baja de vehículo."""
    vehiculo = get_object_or_404(Vehiculo, pk=vehiculo_id)
    if request.method == "POST":
        form = VehiculoForm(request.POST, instance=vehiculo)
        if form.is_valid():
            form.save()
            messages.success(request, "Vehículo actualizado.")
            return redirect("listado_flota")
    else:
        form = VehiculoForm(instance=vehiculo)
    return render(request, "reservas/form_vehiculo.html", {
        "form": form,
        "titulo": f"Editar vehículo: {vehiculo}",
        "vehiculo": vehiculo,
        "usuario": get_usuario_sesion(request),
    })
