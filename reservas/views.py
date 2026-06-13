"""
Vistas tradicionales (templates) para todas las épicas del sistema.

Implementa el flujo HTTP request → template rendering usando Django CBV patterns
con decoradores personalizados. Gestiona autenticación, autorización y lógica
de presentación.

Convención de sesión:
    request.session["usuario_id"]        → PK del usuario logueado
    request.session["es_admin"]          → bool (True si cargo.prioridad == 0)
    request.session["verificacion_uid"]  → PK del usuario durante verificación de correo [NUEVO]

Decoradores de autorización:
    @login_requerido: Redirige a login si no hay sesión activa.
    @admin_requerido: Redirige a inicio si no es administrador.
"""

import calendar
from datetime import date, timedelta, datetime, time

from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q

from .models import Usuario, Vehiculo, Ticket, Cargo
from .forms import (
    RegistroForm, LoginForm, TicketForm, VehiculoSelectorForm,
    FiltroUsuariosForm, FiltroTicketsForm, VehiculoForm,
    VerificacionCodigoForm,          # [NUEVO] formulario de código de 6 dígitos
    AdminCrearUsuarioForm,           # Formulario para admin
)
from .email_verification import (    # [NUEVO] servicio de verificación de correo
    crear_verificacion,
    enviar_correo_verificacion,
    verificar_por_codigo,
    verificar_por_token,
)
from .services import (
    crear_ticket_con_reglas, ResultadoCreacion,
    get_tickets_del_mes, get_tickets_del_dia,
)


ITEMS_PER_PAGE = 20


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS Y DECORADORES
# ══════════════════════════════════════════════════════════════════════════════

def get_usuario_sesion(request):
    """
    Obtiene la instancia del usuario logueado desde la sesión.

    Busca el usuario por su PK almacenado en request.session["usuario_id"].
    Pre-carga la relación con Cargo usando select_related para optimización BD.

    Args:
        request (HttpRequest): Objeto de solicitud HTTP.

    Returns:
        Usuario | None: Instancia del usuario si existe sesión activa,
            None si no hay usuario logueado o fue eliminado.

    Notes:
        Se utiliza select_related("id_cargo") para evitar N+1 queries
        cuando se accede a usuario.id_cargo.nombre o usuario.prioridad.
    """
    uid = request.session.get("usuario_id")
    if not uid:
        return None
    try:
        return Usuario.objects.select_related("id_cargo").get(pk=uid)
    except Usuario.DoesNotExist:
        return None


def paginate_queryset(request, queryset, per_page=ITEMS_PER_PAGE):
    """
    Pagina un queryset y preserva query params distintos de `page`.

    Returns:
        tuple[Page, str]: página actual y querystring sin `page`.
    """
    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(request.GET.get("page"))

    query_params = request.GET.copy()
    query_params.pop("page", None)

    return page_obj, query_params.urlencode()


def login_requerido(view_func):
    """
    Decorador que redirige a login si no hay sesión activa.

    Valida que request.session["usuario_id"] exista. Si no existe,
    redirige a la ruta 'login'. Mantiene el nombre de la vista original
    para introspección.

    Args:
        view_func: Función de vista a proteger.

    Returns:
        wrapper: Función decorada que aplica la validación.

    Notas:
        Patrón simple sin argumentos. Para vistas con parámetros,
        usa *args y **kwargs en wrapper.
    """
    def wrapper(request, *args, **kwargs):
        if not request.session.get("usuario_id"):
            return redirect("login")
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


def admin_requerido(view_func):
    """
    Decorador que redirige si el usuario no es administrador.

    Valida que request.session["es_admin"] sea True. Si es False,
    registra un mensaje de error y redirige al inicio.

    Args:
        view_func: Función de vista a proteger.

    Returns:
        wrapper: Función decorada que aplica la validación.

    Notas:
        Usa messages.error() de Django para notificar al usuario.
        Debe aplicarse DESPUÉS de @login_requerido en pilas de decoradores.
    """
    def wrapper(request, *args, **kwargs):
        if not request.session.get("es_admin"):
            messages.error(request, "No tenés permisos para acceder a esa sección.")
            return redirect("inicio")
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


def chofer_requerido(view_func):
    """
    Decorador que redirige si el usuario no es Chofer.
    """
    def wrapper(request, *args, **kwargs):
        usuario = get_usuario_sesion(request)
        if not usuario or usuario.id_cargo.nombre != Cargo.CHOFER:
            messages.error(request, "No tenés permisos para acceder a esta sección exclusiva para choferes.")
            return redirect("inicio")
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper

def sin_chofer_requerido(view_func):
    """
    Decorador que evita que los Choferes accedan a vistas de usuarios normales.
    Si es chofer, lo redirige a su dashboard.
    """
    def wrapper(request, *args, **kwargs):
        usuario = get_usuario_sesion(request)
        if usuario and usuario.id_cargo.nombre == Cargo.CHOFER:
            return redirect("chofer_dashboard")
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper

# ══════════════════════════════════════════════════════════════════════════════
# ÉPICA 1: AUTENTICACIÓN
# ══════════════════════════════════════════════════════════════════════════════
# HU 1.1: Registro de cuenta
# HU 1.2: Inicio de sesión
# HU 1.3 / 1.4: Panel de validación de usuarios (ver más abajo)


def registro(request):
    """
    Vista para registro de cuenta de usuario (HU 1.1).

    Captura datos de registro y crea un usuario con estado pendiente.
    ACTUALIZADO: ahora incluye verificación de correo electrónico como
    paso previo a la aprobación del administrador.

    Args:
        request (HttpRequest): Objeto de solicitud.
            - GET: Muestra formulario vacío.
            - POST: Procesa envío de datos.

    Returns:
        HttpResponse: Plantilla 'reservas/registro.html' con formulario
            (GET) o redirige a verificar_correo tras éxito (POST).

    Proceso:
        1. GET: Renderiza RegistroForm vacío.
        2. POST (válido):
            a. Crea Usuario con correo_verificado=False, valido=False.
            b. Genera VerificacionCorreo (código 6 dígitos + token UUID).
            c. Envía email con ambos métodos al correo del usuario.
            d. Guarda PK en sesión (verificacion_uid).
            e. Redirige a verificar_correo.
        3. POST (inválido): Re-renderiza formulario con errores.

    Messages:
        - info:    Correo enviado exitosamente con código y enlace.
        - warning: No se pudo enviar el correo (SMTP error).
    """
    if request.method == "POST":
        form = RegistroForm(request.POST)
        if form.is_valid():
            usuario = form.save()  # correo_verificado=False ya está en RegistroForm.save()

            # Si el usuario es Administrador (prioridad 0), no requerir verificación
            if usuario.id_cargo.prioridad == 0:
                usuario.correo_verificado = True
                usuario.save(update_fields=['correo_verificado'])
                messages.success(request, "Cuenta de administrador creada exitosamente. Tu cuenta ya está validada, podés iniciar sesión.")
                return redirect("login")

            # Generar código de 6 dígitos y token UUID simultáneamente
            verificacion = crear_verificacion(usuario)

            # Enviar correo con ambos métodos (código + enlace mágico)
            enviado = enviar_correo_verificacion(usuario, verificacion, request)

            # Guardar PK en sesión para que verificar_correo() sepa a quién verificar
            request.session["verificacion_uid"] = usuario.pk

            if enviado:
                messages.info(
                    request,
                    f"Te enviamos un correo a {usuario.correo} con un código de 6 dígitos "
                    "y un enlace de verificación. Revisá también la carpeta de spam.",
                )
            else:
                # SMTP falló: el usuario puede continuar y pedir reenvío desde la siguiente pantalla
                messages.warning(
                    request,
                    "Tu cuenta fue creada pero no pudimos enviar el correo de verificación. "
                    "Podés solicitar un reenvío desde la siguiente pantalla.",
                )

            return redirect("verificar_correo")
    else:
        form = RegistroForm()
    return render(request, "reservas/registro.html", {"form": form})


def login_view(request):
    """
    Vista para inicio de sesión (HU 1.2).

    Valida credenciales contra la BD y establece sesión. Los usuarios
    pendientes de aprobación o rechazados ven mensajes específicos.

    Args:
        request (HttpRequest): Objeto de solicitud.
            - GET: Muestra formulario de login.
            - POST: Procesa credenciales.

    Returns:
        HttpResponse: Redirige a inicio tras login exitoso,
            o re-renderiza formulario con errores.

    Validaciones:
        1. Si usuario logueado: redirige a inicio.
        2. Si credenciales inválidas: "Correo o contraseña incorrectos."
        3. Si usuario rechazado: "Tu solicitud fue rechazada..."
        4. Si usuario pendiente: "Tu cuenta está pendiente de aprobación..."
        5. Si credenciales correctas y usuario válido: Sesión establecida.

    Sesión (set en request.session):
        - "usuario_id": PK del usuario.
        - "es_admin": bool (cargo.prioridad == 0).

    Messages:
        - error: Credenciales inválidas, rechazado.
        - warning: Pendiente de aprobación.
    """
    if request.session.get("usuario_id"):
        return redirect("inicio")

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

            # [NUEVO] Verificación de correo: bloquear login si el usuario
            # completó el registro pero todavía no verificó su email.
            # Aplica solo si el campo correo_verificado existe en el modelo
            # (requiere haber corrido la migración correspondiente) y si no es Admin.
            if hasattr(usuario, 'correo_verificado') and not usuario.correo_verificado and usuario.id_cargo.prioridad != 0:
                request.session["verificacion_uid"] = usuario.pk
                messages.warning(
                    request,
                    "Primero debés verificar tu correo electrónico. "
                    "Revisá tu bandeja de entrada o solicitá un nuevo código.",
                )
                return redirect("verificar_correo")

            if usuario.rechazado:
                messages.error(request, "Tu solicitud de acceso fue rechazada. Contactá al administrador.")
                return render(request, "reservas/login.html", {"form": form})

            if not usuario.valido:
                messages.warning(request, "Tu cuenta está pendiente de aprobación por un administrador.")
                return render(request, "reservas/login.html", {"form": form})

            # Establecer sesión
            request.session["usuario_id"] = usuario.pk
            request.session["es_admin"] = (usuario.id_cargo.prioridad == 0)
            if usuario.id_cargo.nombre == Cargo.CHOFER:
                return redirect("chofer_dashboard")
            return redirect("inicio")
    else:
        form = LoginForm()
    return render(request, "reservas/login.html", {"form": form})


def logout_view(request):
    """
    Vista para cierre de sesión.

    Elimina todos los datos de sesión y redirige a login.

    Args:
        request (HttpRequest): Objeto de solicitud.

    Returns:
        HttpResponseRedirect: Redirige a 'login'.

    Notes:
        Utiliza request.session.flush() para limpiar completamente la sesión
        (no solo request.session.clear() que mantiene la sesión vacía).
    """
    request.session.flush()
    return redirect("login")


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
    fecha_timeline = None
    horas = []
    page_obj = None
    pagination_query = ""
    total_tickets = 0

    if vehiculo_id:
        try:
            vehiculo_cal = Vehiculo.objects.get(pk=vehiculo_id, activo=True)
            if request.method == "GET":
                form = TicketForm(initial={"id_vehiculo": vehiculo_cal})

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
                
                naive_start = datetime.combine(fecha_timeline, time.min)
                naive_end = datetime.combine(fecha_timeline, time.max)
                
                if is_tz_aware:
                    day_start = timezone.make_aware(naive_start)
                    day_end = timezone.make_aware(naive_end)
                else:
                    day_start = naive_start
                    day_end = naive_end
                    
                for t in tickets_dia:
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

                horas = ["06", "07", "08", "09", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22"]
                total_tickets = page_obj.paginator.count
        except (Vehiculo.DoesNotExist, ValueError):
            pass

    cal = calendar.monthcalendar(anio, mes)
    nombre_mes = date(anio, mes, 1).strftime("%B %Y").capitalize()

    if mes == 1:
        mes_anterior = (anio - 1, 12)
    else:
        mes_anterior = (anio, mes - 1)
    if mes == 12:
        mes_siguiente = (anio + 1, 1)
    else:
        mes_siguiente = (anio, mes + 1)

    return render(request, "reservas/inicio.html", {
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
        "fecha_timeline": fecha_timeline,
        "horas": horas,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_tickets": total_tickets,
        "dia_seleccionado": int(dia_str) if dia_str and dia_str.isdigit() else None,
        "exclusivos_ids": list(Vehiculo.objects.filter(exclusivo_decanato=True).values_list('id', flat=True)),
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
        HttpResponse: Plantilla 'reservas/historial.html' con:
            - tickets: QuerySet de tickets del usuario.
            - usuario: Instancia del usuario logueado.
    """
    usuario = get_usuario_sesion(request)
    form = FiltroTicketsForm(request.GET or None)
    tickets_qs = Ticket.objects.filter(
        id_usuario=usuario
    ).select_related("id_vehiculo").order_by("-hora_inicio")

    if form.is_valid():
        busqueda = form.cleaned_data.get("busqueda")
        vehiculo = form.cleaned_data.get("vehiculo")
        fecha_inicio = form.cleaned_data.get("fecha_inicio")
        fecha_fin = form.cleaned_data.get("fecha_fin")
        
        if busqueda:
            tickets_qs = tickets_qs.filter(
                Q(id_usuario__nombre__icontains=busqueda)
                | Q(id_usuario__apellido__icontains=busqueda)
                | Q(destino__icontains=busqueda)
            )
        if vehiculo:
            tickets_qs = tickets_qs.filter(id_vehiculo=vehiculo)
        if fecha_inicio:
            tickets_qs = tickets_qs.filter(hora_inicio__date__gte=fecha_inicio)
        if fecha_fin:
            tickets_qs = tickets_qs.filter(hora_inicio__date__lte=fecha_fin)

    page_obj, pagination_query = paginate_queryset(request, tickets_qs)

    return render(request, "reservas/historial.html", {
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
        HttpResponse: Plantilla 'reservas/detalle_ticket.html' con ticket.

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
    puede_cancelar = False
    if ticket.estado == Ticket.ESTADO_APROBADO and ticket.hora_inicio >= timezone.now() + timezone.timedelta(days=5):
        puede_cancelar = True

    return render(request, "reservas/detalle_ticket.html", {
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
    from django.contrib import messages
    from .services import cancelar_ticket_usuario
    
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


# ══════════════════════════════════════════════════════════════════════════════
# ÉPICA 8: GESTIÓN DE CHOFERES
# ══════════════════════════════════════════════════════════════════════════════

@login_requerido
@chofer_requerido
def chofer_dashboard(request):
    """
    Vista principal para el chofer.
    Muestra tickets aprobados sin conductor, y sus propios tickets en curso o finalizados.
    """
    usuario = get_usuario_sesion(request)
    
    from django.utils import timezone
    tickets_disponibles_qs = Ticket.objects.filter(
        estado=Ticket.ESTADO_APROBADO, 
        conductor__isnull=True,
        hora_inicio__gte=timezone.now()
    ).select_related('id_vehiculo').order_by('hora_inicio')

    page_obj, pagination_query = paginate_queryset(request, tickets_disponibles_qs)

    # Tickets en curso asignados a este chofer
    tickets_en_curso = Ticket.objects.filter(
        estado=Ticket.ESTADO_EN_CURSO,
        conductor=usuario
    ).select_related('id_vehiculo').order_by('hora_inicio')

    # Historial de tickets finalizados por este chofer
    tickets_finalizados = Ticket.objects.filter(
        estado=Ticket.ESTADO_FINALIZADO,
        conductor=usuario
    ).select_related('id_vehiculo').order_by('-hora_inicio')[:20]

    return render(request, "reservas/chofer_dashboard.html", {
        "usuario": usuario,
        "tickets_disponibles": page_obj.object_list,
        "tickets_en_curso": tickets_en_curso,
        "tickets_finalizados": tickets_finalizados,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
    })

@login_requerido
def aceptar_ticket(request, ticket_id):
    """
    Permite a un chofer o admin asignarse como conductor a un ticket.
    """
    if request.method != "POST":
        return redirect("inicio")

    usuario = get_usuario_sesion(request)
    ticket = get_object_or_404(Ticket, pk=ticket_id)

    # Validar permisos (debe ser chofer o admin)
    if usuario.id_cargo.nombre != Cargo.CHOFER and not request.session.get("es_admin"):
        messages.error(request, "No tenés permisos para aceptar este ticket.")
        return redirect("inicio")

    # Validar que el chofer no tenga otro viaje a la misma hora
    if Ticket.objects.filter(conductor=usuario, estado=Ticket.ESTADO_EN_CURSO, hora_inicio=ticket.hora_inicio).exclude(pk=ticket.pk).exists():
        messages.error(request, "No podés aceptar este viaje porque ya tenés otro asignado con la misma hora de salida.")
        if request.session.get("es_admin"):
            return redirect("monitor_tickets_activos")
        return redirect("chofer_dashboard")

    if ticket.estado == Ticket.ESTADO_APROBADO and ticket.conductor is None:
        ticket.conductor = usuario
        ticket.estado = Ticket.ESTADO_EN_CURSO
        ticket.save(update_fields=['conductor', 'estado'])
        messages.success(request, f"Te has asignado como conductor del ticket #{ticket.pk}.")
    else:
        messages.error(request, "El ticket no está disponible para asignación.")

    if request.session.get("es_admin"):
        return redirect("monitor_tickets_activos")
    return redirect("chofer_dashboard")

@login_requerido
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
            ticket.estado = Ticket.ESTADO_FINALIZADO
            ticket.save(update_fields=['estado'])
            messages.success(request, f"El ticket #{ticket.pk} ha sido finalizado.")
        else:
            messages.error(request, "El ticket no está en curso.")
    else:
        messages.error(request, "No tenés permisos para finalizar este ticket.")

    if request.session.get("es_admin"):
        return redirect("monitor_tickets_activos")
    return redirect("chofer_dashboard")



# ══════════════════════════════════════════════════════════════════════════════
# ÉPICA 5: GESTIÓN Y SUPERVISIÓN ADMINISTRATIVA
# ══════════════════════════════════════════════════════════════════════════════
# HU 1.3 / 1.4: Panel de validación de usuarios pendientes
# HU 5.1: Directorio de usuarios
# HU 5.2: Vista de usuarios rechazados
# HU 5.3: Monitor de tickets activos
# HU 5.4: Auditoría de tickets históricos


@login_requerido
@admin_requerido
def panel_validacion(request):
    """
    Vista del panel de validación de usuarios pendientes (HU 1.3, 1.4).

    Muestra lista de usuarios con valido=False y rechazado=False.
    El admin puede aprobar (valido=True) o rechazar (rechazado=True).

    Args:
        request (HttpRequest): Objeto de solicitud.
            - GET: Muestra lista de pendientes.
            - POST: Procesa acción (aprobar/rechazar).

    POST:
        Parámetros:
            - usuario_id (int): PK del usuario.
            - accion (str): "aprobar" o "rechazar".

    Returns:
        HttpResponse: Plantilla 'reservas/panel_validacion.html'
            - pendientes: QuerySet de usuarios pendientes.
            - usuario: Instancia del usuario logueado (admin).

    Redirección (POST):
        - Redirect a panel_validacion tras procesar.

    Messages (POST):
        - success: "{nombre} fue aprobado."
        - warning: "{nombre} fue rechazado."

    Notes:
        - Utiliza update_fields=["valido", "rechazado"] para optimización.
        - Ambas acciones redirigen a la misma vista (GET).
    """
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
            
            from django_q.tasks import async_task
            from django.conf import settings
            from django.template.loader import render_to_string
            import logging
            
            try:
                asunto = "Sistema de Reserva de Vehículos — Solicitud rechazada"
                mensaje = ( # default por si falla el html 
                    f"Hola {usuario_objetivo.nombre},\n\n"
                    "Te informamos que tu solicitud para acceder al Sistema de Reserva de Vehículos "
                    "ha sido rechazada por un administrador.\n\n"
                    "Si creés que esto es un error, por favor contactate con el administrador del sistema.\n\n"
                    "— Sistema de Reserva de Vehículos"
                )
                html_message = render_to_string(
                    "reservas/emails/account_rejected.html",
                    {"usuario": usuario_objetivo}
                )
                async_task(
                    "reservas.tasks.enviar_correo_async",
                    subject=asunto,
                    message=mensaje,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[usuario_objetivo.correo],
                    html_message=html_message,
                    fail_silently=True,
                )
            except Exception as exc:
                logger = logging.getLogger(__name__)
                logger.error("Error al enviar correo de rechazo a %s: %s", usuario_objetivo.correo, exc)

            messages.warning(request, f"{usuario_objetivo.nombre_completo} fue rechazado.")

        return redirect("panel_validacion")

    return render(request, "reservas/panel_validacion.html", {
        "pendientes": pendientes,
        "usuario": get_usuario_sesion(request),
    })


@login_requerido
@admin_requerido
def usuarios(request):
    """
    Vista de usuarios con búsqueda y filtros (HU 5.1).

    Muestra lista de usuarios aprobados (valido=True). Permite buscar
    por nombre/apellido/correo y filtrar por cargo.

    Args:
        request (HttpRequest): Objeto de solicitud (GET).
            Parámetros:
            - busqueda (str): Busca en nombre, apellido, correo (icontains).
            - cargo (int): PK de cargo para filtrar.

    Returns:
        HttpResponse: Plantilla 'reservas/usuarios.html' con:
            - form: FiltroUsuariosForm.
            - usuarios: QuerySet filtrado de usuarios válidos.
            - usuario: Instancia del usuario logueado (admin).

    Notas:
        - Solo usuarios con valido=True se muestran.
        - Ambos filtros son opcionales (required=False).
        - Q() permite búsqueda OR en múltiples campos.
    """
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

    page_obj, pagination_query = paginate_queryset(request, usuarios)

    return render(request, "reservas/usuarios.html", {
        "form": form,
        "usuarios": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_usuarios": page_obj.paginator.count,
        "usuario": get_usuario_sesion(request),
    })

@login_requerido
@admin_requerido
def admin_crear_usuario(request):
    """
    Vista para que un administrador pueda crear usuarios directamente.
    Los usuarios creados nacen validados.
    """
    if request.method == "POST":
        form = AdminCrearUsuarioForm(request.POST)
        if form.is_valid():
            usuario = form.save()
            messages.success(request, f"Usuario {usuario.nombre_completo} creado exitosamente.")
            return redirect("usuarios")
    else:
        form = AdminCrearUsuarioForm()
    
    return render(request, "reservas/admin_crear_usuario.html", {
        "form": form,
        "usuario": get_usuario_sesion(request),
    })


@login_requerido
@admin_requerido
def usuarios_rechazados(request):
    """
    Vista de usuarios rechazados (HU 5.2).

    Muestra lista de todos los usuarios con rechazado=True.
    Útil para auditoría y revisión de solicitudes denegadas.

    Args:
        request (HttpRequest): Objeto de solicitud (GET).

    Returns:
        HttpResponse: Plantilla 'reservas/usuarios_rechazados.html' con:
            - rechazados: QuerySet de usuarios rechazados.
            - usuario: Instancia del usuario logueado (admin).
    """
    rechazados_qs = Usuario.objects.filter(rechazado=True).select_related("id_cargo")
    page_obj, pagination_query = paginate_queryset(request, rechazados_qs)

    return render(request, "reservas/usuarios_rechazados.html", {
        "rechazados": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_rechazados": page_obj.paginator.count,
        "usuario": get_usuario_sesion(request),
    })


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
        HttpResponse: Plantilla 'reservas/monitor_activos.html' con:
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
    ).select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo").order_by("hora_inicio")

    if form.is_valid():
        busqueda = form.cleaned_data.get("busqueda")
        vehiculo = form.cleaned_data.get("vehiculo")
        cargo = form.cleaned_data.get("cargo")
        fecha_inicio = form.cleaned_data.get("fecha_inicio")
        fecha_fin = form.cleaned_data.get("fecha_fin")
        
        if busqueda:
            tickets_qs = tickets_qs.filter(
                Q(id_usuario__nombre__icontains=busqueda)
                | Q(id_usuario__apellido__icontains=busqueda)
                | Q(destino__icontains=busqueda)
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

    return render(request, "reservas/monitor_activos.html", {
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
        HttpResponse: Plantilla 'reservas/historial_tickets.html' con:
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
        Q(estado=Ticket.ESTADO_CANCELADO) | Q(hora_inicio__lt=date.today())
    ).select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo").order_by("-hora_inicio")

    if form.is_valid():
        busqueda = form.cleaned_data.get("busqueda")
        vehiculo = form.cleaned_data.get("vehiculo")
        cargo = form.cleaned_data.get("cargo")
        fecha_inicio = form.cleaned_data.get("fecha_inicio")
        fecha_fin = form.cleaned_data.get("fecha_fin")
        
        if busqueda:
            tickets_qs = tickets_qs.filter(
                Q(id_usuario__nombre__icontains=busqueda)
                | Q(id_usuario__apellido__icontains=busqueda)
                | Q(destino__icontains=busqueda)
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

    return render(request, "reservas/historial_tickets.html", {
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
    import csv
    from django.http import HttpResponse
    
    form = FiltroTicketsForm(request.GET or None)
    tickets_qs = Ticket.objects.filter(
        Q(estado=Ticket.ESTADO_CANCELADO) | Q(hora_inicio__lt=date.today())
    ).select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo").order_by("-hora_inicio")

    if form.is_valid():
        busqueda = form.cleaned_data.get("busqueda")
        vehiculo = form.cleaned_data.get("vehiculo")
        cargo = form.cleaned_data.get("cargo")
        fecha_inicio = form.cleaned_data.get("fecha_inicio")
        fecha_fin = form.cleaned_data.get("fecha_fin")
        
        if busqueda:
            tickets_qs = tickets_qs.filter(
                Q(id_usuario__nombre__icontains=busqueda)
                | Q(id_usuario__apellido__icontains=busqueda)
                | Q(destino__icontains=busqueda)
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

# ══════════════════════════════════════════════════════════════════════════════
# ÉPICA 6: ABM (ALTA, BAJA, MODIFICACIÓN) DE FLOTA
# ══════════════════════════════════════════════════════════════════════════════
# HU 6.1: Listado de vehículos
# HU 6.2: Alta de vehículo
# HU 6.3: Edición / baja de vehículo


@login_requerido
@admin_requerido
def listado_flota(request):
    """
    Vista del listado de vehículos de la flota (HU 6.1).

    Muestra todos los vehículos (activos e inactivos) ordenados
    por marca y modelo. Desde aquí se puede navegar a crear o editar.

    Args:
        request (HttpRequest): Objeto de solicitud (GET).

    Returns:
        HttpResponse: Plantilla 'reservas/listado_flota.html' con:
            - vehiculos: QuerySet de todos los vehículos.
            - usuario: Instancia del usuario logueado (admin).
    """
    vehiculos_decano = Vehiculo.objects.filter(exclusivo_decanato=True).order_by("marca", "modelo")
    vehiculos_qs = Vehiculo.objects.filter(exclusivo_decanato=False).order_by("marca", "modelo")
    page_obj, pagination_query = paginate_queryset(request, vehiculos_qs)

    return render(request, "reservas/listado_flota.html", {
        "vehiculos_decano": vehiculos_decano,
        "vehiculos": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_vehiculos": page_obj.paginator.count,
        "total_vehiculos_activos": vehiculos_qs.filter(activo=True).count(),
        "usuario": get_usuario_sesion(request),
    })


@login_requerido
@admin_requerido
def alta_vehiculo(request):
    """
    Vista para dar de alta un nuevo vehículo (HU 6.2).

    Captura datos de marca, modelo, capacidad y estado activo.
    La creación es inmediata sin validaciones adicionales.

    Args:
        request (HttpRequest): Objeto de solicitud.
            - GET: Muestra VehiculoForm vacío.
            - POST: Procesa creación de vehículo.

    Returns:
        HttpResponse: Plantilla 'reservas/form_vehiculo.html' con:
            - form: VehiculoForm.
            - titulo: "Agregar vehículo".
            - usuario: Instancia del usuario logueado (admin).

    Redirección (POST exitoso):
        - Redirect a listado_flota.

    Messages (POST):
        - success: "Vehículo agregado a la flota."
    """
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
    """
    Vista para editar o dar de baja un vehículo (HU 6.3).

    Permite modificar marca, modelo, capacidad y estado (activo/inactivo).
    Cambiar a inactivo impide que aparezca en formularios de reserva.

    Args:
        request (HttpRequest): Objeto de solicitud.
            - GET: Muestra VehiculoForm pre-poblado.
            - POST: Procesa actualización.
        vehiculo_id (int): PK del vehículo.

    Returns:
        HttpResponse: Plantilla 'reservas/form_vehiculo.html' con:
            - form: VehiculoForm pre-poblado.
            - titulo: "Editar vehículo: {marca} {modelo}".
            - vehiculo: Instancia del vehículo.
            - usuario: Instancia del usuario logueado (admin).

    Redirección (POST exitoso):
        - Redirect a listado_flota.

    Messages (POST):
        - success: "Vehículo actualizado."

    Raises:
        Http404: Si el vehículo no existe.

    Notas:
        - No hay "eliminación" física, solo cambiar activo=False.
        - Los tickets existentes permanecen (PROTECT en ForeignKey).
    """
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


# ══════════════════════════════════════════════════════════════════════════════
# ÉPICA 7: ANALÍTICAS Y REPORTES (ADMIN ONLY)
# ══════════════════════════════════════════════════════════════════════════════

@login_requerido
@admin_requerido
def reporte_analiticas(request):
    """
    Vista de analíticas y reportes narrativos de la flota (admin only).

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
    from django.db.models import Count
    from django.db.models.functions import TruncMonth
    from django.utils import timezone
    from datetime import timedelta

    usuario = get_usuario_sesion(request)
    rango = request.GET.get("rango", "30d")

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
        if desde:
            return qs.filter(hora_inicio__gte=desde)
        return qs

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

        horas_efectivas = 0.0
        for t in t_aprobados.exclude(hora_fin__isnull=True):
            delta = t.hora_fin - t.hora_inicio
            horas_efectivas += delta.total_seconds() / 3600

        horas_efectivas = round(horas_efectivas, 1)
        if horas_efectivas > max_horas:
            max_horas = horas_efectivas

        tasa_cancel = round(
            (count_cancelados / count_total * 100) if count_total > 0 else 0, 1
        )

        stats_vehiculos.append({
            "vehiculo":         v,
            "count_aprobados":  count_aprobados,
            "count_cancelados": count_cancelados,
            "count_total":      count_total,
            "horas_efectivas":  horas_efectivas,
            "tasa_cancelacion": tasa_cancel,
        })

    for sv in stats_vehiculos:
        sv["barra_pct"] = round(
            (sv["horas_efectivas"] / max_horas * 100) if max_horas > 0 else 0
        )

    stats_vehiculos.sort(key=lambda x: x["horas_efectivas"], reverse=True)

    horas_totales = sum(sv["horas_efectivas"] for sv in stats_vehiculos)

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

    # ── Usuarios y flota ─────────────────────────────────────────────────────
    total_usuarios_activos    = Usuario.objects.filter(valido=True).count()
    total_usuarios_pendientes = Usuario.objects.filter(valido=False, rechazado=False).count()
    total_vehiculos_activos   = Vehiculo.objects.filter(activo=True).count()
    total_vehiculos_inactivos = Vehiculo.objects.filter(activo=False).count()

    # ── Insights narrativos ───────────────────────────────────────────────────
    insights = []

    if stats_vehiculos and stats_vehiculos[0]["horas_efectivas"] > 0:
        lider = stats_vehiculos[0]
        pct_lider = round(
            lider["horas_efectivas"] / horas_totales * 100
        ) if horas_totales > 0 else 0
        insights.append(
            f"El {lider['vehiculo'].marca} {lider['vehiculo'].modelo} concentra "
            f"el {pct_lider}% del tiempo efectivo de uso de la flota "
            f"({lider['horas_efectivas']}h en {rango_label.lower()})."
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
                f"{diff} puntos por encima del promedio de la flota."
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
    top_usuarios = tickets_periodo.values(
        'id_usuario__nombre', 'id_usuario__apellido', 'id_usuario__id_cargo__nombre'
    ).annotate(
        total=Count('id')
    ).order_by('-total')[:5]

    solicitudes_cargo = tickets_periodo.values(
        'id_usuario__id_cargo__nombre'
    ).annotate(
        total=Count('id')
    ).order_by('-total')

    return render(request, "reservas/analiticas.html", {
        "usuario":                   usuario,
        "rango":                     rango,
        "rango_label":               rango_label,
        "stats_vehiculos":           stats_vehiculos,
        "total_tickets":             total_tickets,
        "total_aprobados":           total_aprobados,
        "total_cancelados":          total_cancelados,
        "total_pendientes_tickets":  total_pendientes_tickets,
        "tasa_cancelacion_global":   tasa_cancelacion_global,
        "horas_totales":             round(horas_totales, 1),
        "mes_pico_label":            mes_pico_label,
        "mes_pico_count":            mes_pico_count,
        "duracion_promedio":         duracion_promedio,
        "total_usuarios_activos":    total_usuarios_activos,
        "total_usuarios_pendientes": total_usuarios_pendientes,
        "total_vehiculos_activos":   total_vehiculos_activos,
        "total_vehiculos_inactivos": total_vehiculos_inactivos,
        "insights":                  insights,
        "top_usuarios":              top_usuarios,
        "solicitudes_cargo":         solicitudes_cargo,
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
    import io
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from django.utils import timezone
    from django.db.models import Count
    from django.db.models.functions import TruncMonth
    from datetime import timedelta
    from weasyprint import HTML

    usuario = get_usuario_sesion(request)
    rango = request.GET.get("rango", "30d")

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
        return qs.filter(hora_inicio__gte=desde) if desde else qs

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
        horas_efectivas  = 0.0
        for t in t_aprobados.exclude(hora_fin__isnull=True):
            horas_efectivas += (t.hora_fin - t.hora_inicio).total_seconds() / 3600
        horas_efectivas = round(horas_efectivas, 1)
        if horas_efectivas > max_horas:
            max_horas = horas_efectivas
        stats_vehiculos.append({
            "vehiculo":         v,
            "count_aprobados":  count_aprobados,
            "count_cancelados": count_cancelados,
            "count_total":      count_total,
            "horas_efectivas":  horas_efectivas,
            "tasa_cancelacion": round((count_cancelados / count_total * 100) if count_total > 0 else 0, 1),
        })

    for sv in stats_vehiculos:
        sv["barra_pct"] = round((sv["horas_efectivas"] / max_horas * 100) if max_horas > 0 else 0)
    stats_vehiculos.sort(key=lambda x: x["horas_efectivas"], reverse=True)
    horas_totales = sum(sv["horas_efectivas"] for sv in stats_vehiculos)

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
    top_usuarios = tickets_periodo.values(
        'id_usuario__nombre', 'id_usuario__apellido', 'id_usuario__id_cargo__nombre'
    ).annotate(
        total=Count('id')
    ).order_by('-total')[:5]

    solicitudes_cargo = tickets_periodo.values(
        'id_usuario__id_cargo__nombre'
    ).annotate(
        total=Count('id')
    ).order_by('-total')

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
        "horas_totales":             round(horas_totales, 1),
        "mes_pico_label":            mes_pico_label,
        "mes_pico_count":            mes_pico_count,
        "duracion_promedio":         duracion_promedio,
        "total_usuarios_activos":    Usuario.objects.filter(valido=True).count(),
        "total_usuarios_pendientes": Usuario.objects.filter(valido=False, rechazado=False).count(),
        "total_vehiculos_activos":   Vehiculo.objects.filter(activo=True).count(),
        "total_vehiculos_inactivos": Vehiculo.objects.filter(activo=False).count(),
        "fecha_generacion":          f"{hoy.day} de {_MESES_ES[hoy.month]} de {hoy.year}",
        "top_usuarios":              top_usuarios,
        "solicitudes_cargo":         solicitudes_cargo,
    }

    html_string = render_to_string("reservas/analiticas_pdf.html", context)
    pdf_bytes = HTML(string=html_string).write_pdf()

    filename = f"analiticas_{rango}_{hoy.strftime('%Y%m%d')}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ══════════════════════════════════════════════════════════════════════════════
# ÉPICA 1 — VERIFICACIÓN DE CORREO ELECTRÓNICO [NUEVO]
# ══════════════════════════════════════════════════════════════════════════════
# Extensión de HU 1.1: flujo de confirmación de email post-registro.
# El usuario debe verificar su correo antes de poder iniciar sesión,
# independientemente de la aprobación del administrador.


def verificar_correo(request):
    """
    Vista del formulario de verificación de correo electrónico (extensión HU 1.1).

    Muestra el formulario de código de 6 dígitos y permite reenviar el email.
    Se llega aquí desde registro() o desde login_view() si el correo no fue
    verificado todavía.

    Args:
        request (HttpRequest): Objeto de solicitud.
            - GET:  Muestra el formulario vacío con los dos tabs (código / enlace).
            - POST (sin accion):  Valida el código ingresado.
            - POST (accion="reenviar"): Regenera código/token y reenvía el correo.

    Returns:
        HttpResponse: Plantilla 'reservas/verificar_correo.html' con:
            - form:   VerificacionCodigoForm (vacío o con errores).
            - correo: Email del usuario (para mostrarlo en pantalla).
        O redirect a login (verificación exitosa) o registro (sesión perdida).

    Protecciones:
        - Sin verificacion_uid en sesión → redirige al registro.
        - Usuario ya verificado → redirige al login con mensaje de éxito.

    Session:
        Lee:   request.session["verificacion_uid"]
        Borra: request.session["verificacion_uid"] al verificar exitosamente.
    """
    uid = request.session.get("verificacion_uid")
    if not uid:
        # Sesión perdida o acceso directo a la URL sin registrarse antes
        messages.error(request, "Sesión de verificación no encontrada. Registrate nuevamente.")
        return redirect("registro")

    try:
        usuario = Usuario.objects.get(pk=uid)
    except Usuario.DoesNotExist:
        return redirect("registro")

    # Si ya verificó (ej: abrió el enlace mágico en otra pestaña), ir al login
    if hasattr(usuario, 'correo_verificado') and usuario.correo_verificado:
        messages.success(request, "Tu correo ya fue verificado. Podés iniciar sesión.")
        return redirect("login")

    if request.method == "POST":
        accion = request.POST.get("accion")

        # ── Reenvío: elimina registro anterior y genera uno nuevo ──────────
        if accion == "reenviar":
            verificacion = crear_verificacion(usuario)
            enviado = enviar_correo_verificacion(usuario, verificacion, request)
            if enviado:
                messages.success(request, "Código reenviado. Revisá tu bandeja de entrada.")
            else:
                messages.error(request, "No se pudo enviar el correo. Intentá de nuevo en unos minutos.")
            return redirect("verificar_correo")

        # ── Validación del código ingresado ────────────────────────────────
        form = VerificacionCodigoForm(request.POST)
        if form.is_valid():
            codigo = form.cleaned_data["codigo"]
            resultado = verificar_por_codigo(usuario, codigo)

            if resultado.exito:
                # Limpiar sesión de verificación (ya no es necesaria)
                del request.session["verificacion_uid"]
                messages.success(
                    request,
                    "✓ Correo verificado correctamente. "
                    "Tu solicitud quedó pendiente de aprobación por un administrador.",
                )
                return redirect("login")
            else:
                # Código incorrecto, expirado o ya usado → mostrar mensaje descriptivo
                messages.error(request, resultado.mensaje)
    else:
        form = VerificacionCodigoForm()

    from .models import VerificacionCorreo
    from django.utils import timezone
    try:
        verificacion = VerificacionCorreo.objects.get(usuario=usuario)
        tiempo_transcurrido = (timezone.now() - verificacion.creado_en).total_seconds()
        segundos_restantes = int(max(0, 30 * 60 - tiempo_transcurrido))
    except VerificacionCorreo.DoesNotExist:
        segundos_restantes = 0

    return render(request, "reservas/verificar_correo.html", {
        "form": form,
        "correo": usuario.correo,
        "segundos_restantes": segundos_restantes,
    })


def verificar_correo_enlace(request, token):
    """
    Vista del enlace mágico de verificación (extensión HU 1.1).

    Se activa cuando el usuario hace clic en el botón del correo electrónico.
    El token llega como parámetro UUID, validado por el conversor <uuid:>
    en urls.py antes de llegar aquí (no llegan strings malformados).

    Flujo según resultado de verificar_por_token():
        OK:           limpia sesión → redirect login (éxito).
        EXPIRADO:     guarda uid en sesión → redirect verificar_correo (pedir reenvío).
        YA_USADO:     guarda uid en sesión → redirect verificar_correo (informar).
        INCORRECTO:   token no existe en BD → redirect login (error).

    Args:
        request (HttpRequest): Solo GET (el enlace del correo es siempre GET).
        token (uuid.UUID): Token UUID del enlace, ya validado por Django.

    Returns:
        HttpResponseRedirect: Redirect al login o a verificar_correo.
    """
    resultado, usuario = verificar_por_token(token)

    if resultado.exito:
        # Limpiar sesión de verificación si el usuario tenía el form abierto en paralelo
        request.session.pop("verificacion_uid", None)
        messages.success(
            request,
            "✓ Correo verificado correctamente. "
            "Tu solicitud quedó pendiente de aprobación por un administrador.",
        )

    else:
        # Guardar uid en sesión para que pueda pedir reenvío desde verificar_correo
        if usuario:
            request.session["verificacion_uid"] = usuario.pk

        messages.error(request, resultado.mensaje)

        # Si expiró o ya fue usado, mandarlo a la pantalla de verificación para reenviar
        if resultado.estado in (resultado.EXPIRADO, resultado.YA_USADO):
            return redirect("verificar_correo")

    return redirect("login")

# ══════════════════════════════════════════════════════════════════════════════
# Flujo de Recuperación de Contraseña
# ══════════════════════════════════════════════════════════════════════════════

def solicitar_recuperacion(request):
    from .forms import SolicitarRecuperacionForm
    from .password_recovery import crear_recuperacion, enviar_correo_recuperacion

    if request.method == "POST":
        form = SolicitarRecuperacionForm(request.POST)
        if form.is_valid():
            correo = form.cleaned_data["correo"]
            try:
                usuario = Usuario.objects.get(correo=correo)
                recuperacion = crear_recuperacion(usuario)
                enviar_correo_recuperacion(usuario, recuperacion, request)
                request.session["recuperacion_uid"] = usuario.pk
                messages.info(request, "Te hemos enviado un correo con instrucciones para restablecer tu contraseña.")
                return redirect("verificar_recuperacion")
            except Usuario.DoesNotExist:
                # No revelar si el correo existe o no por seguridad,
                # solo mostrar el mismo mensaje de éxito.
                messages.info(request, "Si el correo está registrado, recibirás instrucciones en unos minutos.")
                return redirect("login")
    else:
        form = SolicitarRecuperacionForm()

    return render(request, "reservas/solicitar_recuperacion.html", {"form": form})


def verificar_recuperacion(request):
    from .forms import VerificarRecuperacionForm
    from .password_recovery import verificar_recuperacion_por_codigo, crear_recuperacion, enviar_correo_recuperacion
    from .models import RecuperacionPassword
    from django.utils import timezone

    uid = request.session.get("recuperacion_uid")
    if not uid:
        messages.error(request, "Sesión de recuperación inválida o expirada.")
        return redirect("solicitar_recuperacion")

    try:
        usuario = Usuario.objects.get(pk=uid)
    except Usuario.DoesNotExist:
        return redirect("solicitar_recuperacion")

    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "reenviar":
            recuperacion = crear_recuperacion(usuario)
            enviar_correo_recuperacion(usuario, recuperacion, request)
            messages.success(request, "Código reenviado. Revisá tu correo.")
            return redirect("verificar_recuperacion")

        form = VerificarRecuperacionForm(request.POST)
        if form.is_valid():
            codigo = form.cleaned_data["codigo"]
            resultado = verificar_recuperacion_por_codigo(usuario, codigo)
            
            if resultado.exito:
                request.session["can_reset_password"] = True
                messages.success(request, "Código verificado. Ahora podés ingresar tu nueva contraseña.")
                return redirect("nueva_contrasena")
            else:
                messages.error(request, resultado.mensaje)
    else:
        form = VerificarRecuperacionForm()

    try:
        recuperacion = RecuperacionPassword.objects.get(usuario=usuario)
        tiempo_transcurrido = (timezone.now() - recuperacion.creado_en).total_seconds()
        segundos_restantes = int(max(0, 30 * 60 - tiempo_transcurrido))
    except RecuperacionPassword.DoesNotExist:
        segundos_restantes = 0

    return render(request, "reservas/verificar_recuperacion.html", {
        "form": form,
        "correo": usuario.correo,
        "segundos_restantes": segundos_restantes,
    })


def verificar_recuperacion_enlace(request, token):
    from .password_recovery import verificar_recuperacion_por_token

    resultado, usuario = verificar_recuperacion_por_token(token)
    
    if resultado.exito:
        request.session["recuperacion_uid"] = usuario.pk
        request.session["can_reset_password"] = True
        messages.success(request, "Enlace verificado. Ingresá tu nueva contraseña.")
        return redirect("nueva_contrasena")
    else:
        messages.error(request, resultado.mensaje)
        return redirect("login")


def nueva_contrasena(request):
    from .forms import NuevaContrasenaForm
    from .password_recovery import consumir_recuperacion

    uid = request.session.get("recuperacion_uid")
    can_reset = request.session.get("can_reset_password")

    if not uid or not can_reset:
        messages.error(request, "No tenés permiso para cambiar la contraseña en este momento.")
        return redirect("solicitar_recuperacion")

    try:
        usuario = Usuario.objects.get(pk=uid)
    except Usuario.DoesNotExist:
        return redirect("solicitar_recuperacion")

    if request.method == "POST":
        form = NuevaContrasenaForm(request.POST)
        if form.is_valid():
            usuario.set_password(form.cleaned_data["contrasena_nueva"])
            usuario.save(update_fields=["contrasena"])
            consumir_recuperacion(usuario)
            
            # Limpiar sesión
            request.session.pop("recuperacion_uid", None)
            request.session.pop("can_reset_password", None)
            
            messages.success(request, "Tu contraseña ha sido restablecida exitosamente. Ya podés iniciar sesión.")
            return redirect("login")
    else:
        form = NuevaContrasenaForm()

    return render(request, "reservas/nueva_contrasena.html", {"form": form})
