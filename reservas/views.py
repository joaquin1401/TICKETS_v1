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
from decimal import Decimal, InvalidOperation

from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q

from .models import Usuario, Vehiculo, Ticket, Cargo, ConfiguracionGlobal, Feriado
from .forms import (
    RegistroForm, LoginForm, TicketForm, VehiculoSelectorForm,
    FiltroUsuariosForm, FiltroTicketsForm, VehiculoForm,
    VerificacionCodigoForm,          # [NUEVO] formulario de código de 6 dígitos
    AdminCrearUsuarioForm, AdminEditarUsuarioForm,           # Formulario para admin
    ConfiguracionGlobalForm,
)
from .utils.email_verification import (    # [NUEVO] servicio de verificación de correo
    crear_verificacion,
    enviar_correo_verificacion,
    verificar_por_codigo,
    verificar_por_token,
)
from .utils.services import (
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
        if not usuario or (usuario.id_cargo.nombre != Cargo.CHOFER and not request.session.get("es_admin")):
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

def custom_404(request, exception=None):
    """
    Manejador personalizado para el error 404.
    Muestra una página indicando que la ruta no existe.
    """
    return render(request, "reservas/404.html", status=404)

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
        HttpResponse: Plantilla 'reservas/auth/registro.html' con formulario
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
    return render(request, "reservas/auth/registro.html", {"form": form})


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
                return render(request, "reservas/auth/login.html", {"form": form})

            if not usuario.check_password(contrasena):
                messages.error(request, "Correo o contraseña incorrectos.")
                return render(request, "reservas/auth/login.html", {"form": form})

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
                return render(request, "reservas/auth/login.html", {"form": form})

            if not usuario.valido:
                messages.warning(request, "Tu cuenta está pendiente de aprobación por un administrador.")
                return render(request, "reservas/auth/login.html", {"form": form})

            # Establecer sesión
            request.session["usuario_id"] = usuario.pk
            request.session["es_admin"] = (usuario.id_cargo.prioridad == 0)
            if usuario.id_cargo.nombre == Cargo.CHOFER:
                return redirect("chofer_dashboard")
            return redirect("inicio")
    else:
        form = LoginForm()
    return render(request, "reservas/auth/login.html", {"form": form})


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
    es_admin = usuario.id_cargo.prioridad == 0
    es_usuario_general = usuario.id_cargo.nombre == Cargo.USUARIO
    form = TicketForm(es_admin=es_admin, es_usuario_general=es_usuario_general)

    if request.method == "POST":
        form = TicketForm(request.POST, es_admin=es_admin, es_usuario_general=es_usuario_general)
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
    puede_cancelar = False
    if ticket.estado == Ticket.ESTADO_APROBADO and ticket.hora_inicio >= timezone.now() + timezone.timedelta(days=5):
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
    from django.contrib import messages
    from .utils.services import cancelar_ticket_usuario
    
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
    Panel principal del chofer. Muestra en una sola pantalla:
      - Viajes en curso (asignados y activos)
      - Viajes de hoy (fecha de inicio = hoy, aún no iniciados)
      - Viajes futuros (aprobados sin conductor, con inicio después de hoy)
    """
    usuario = get_usuario_sesion(request)
    from datetime import date

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
            from django.utils.timezone import make_aware, is_naive, localtime
            from datetime import datetime
            
            try:
                ticket.kilometraje_fin = Decimal(km_fin_str)
                
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
                
            if ticket.hora_fin_real < ticket.hora_inicio_real:
                messages.error(request, "La hora de regreso no puede ser anterior a la hora de salida.")
                return redirect(request.META.get('HTTP_REFERER', 'inicio'))
                
            if ticket.kilometraje_inicio is not None and ticket.kilometraje_fin < ticket.kilometraje_inicio:
                messages.error(request, f"El kilometraje de regreso no puede ser menor al de salida ({ticket.kilometraje_inicio}).")
                return redirect(request.META.get('HTTP_REFERER', 'inicio'))
                
            # Validar justificación por retraso > 2h (comparando con la HORA ACTUAL de Argentina, no la ingresada)
            if ticket.hora_fin:
                from django.utils.timezone import localtime
                retraso = localtime(timezone.now()) - localtime(ticket.hora_fin)
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
        HttpResponse: Plantilla 'reservas/usuarios/panel_validacion.html'
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

    return render(request, "reservas/usuarios/panel_validacion.html", {
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
        HttpResponse: Plantilla 'reservas/usuarios/usuarios.html' con:
            - form: FiltroUsuariosForm.
            - usuarios: QuerySet filtrado de usuarios válidos.
            - usuario: Instancia del usuario logueado (admin).

    Notas:
        - Solo usuarios con valido=True se muestran.
        - Ambos filtros son opcionales (required=False).
        - Q() permite búsqueda OR en múltiples campos.
    """
    form = FiltroUsuariosForm(request.GET or None)
    usuarios = Usuario.objects.exclude(valido=False, rechazado=False).select_related("id_cargo")

    if form.is_valid():
        busqueda = form.cleaned_data.get("busqueda")
        cargo = form.cleaned_data.get("cargo")
        if busqueda:
            q_objects = Q()
            for palabra in busqueda.split():
                q_objects.add(
                    Q(nombre__icontains=palabra)
                    | Q(apellido__icontains=palabra)
                    | Q(correo__icontains=palabra),
                    Q.AND
                )
            usuarios = usuarios.filter(q_objects)
        if cargo:
            usuarios = usuarios.filter(id_cargo=cargo)

    page_obj, pagination_query = paginate_queryset(request, usuarios)

    return render(request, "reservas/usuarios/usuarios.html", {
        "form": form,
        "usuarios": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_usuarios": page_obj.paginator.count,
        "usuario": get_usuario_sesion(request),
    })

@login_requerido
@admin_requerido
def detalle_usuario(request, usuario_id):
    """
    Vista de detalle de un usuario y su historial de tickets.
    Permite a los administradores (SEU) desactivar la cuenta o editar los datos del usuario.
    """
    usuario_detalle = get_object_or_404(Usuario, pk=usuario_id)
    
    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "desactivar":
            if usuario_detalle.id_cargo.prioridad == 0:
                messages.error(request, "No podés desactivar a un Administrador SEU.")
            else:
                usuario_detalle.valido = False
                usuario_detalle.rechazado = True
                usuario_detalle.save(update_fields=["valido", "rechazado"])
                messages.success(request, f"El usuario {usuario_detalle.nombre_completo} ha sido desactivado.")
            return redirect("usuarios")
        elif accion == "editar":
            form = AdminEditarUsuarioForm(request.POST, instance=usuario_detalle)
            if form.is_valid():
                form.save()
                messages.success(request, f"Los datos de {usuario_detalle.nombre_completo} han sido actualizados.")
                return redirect("detalle_usuario", usuario_id=usuario_detalle.pk)
            else:
                messages.error(request, "Hubo un error al actualizar los datos. Revisá el formulario.")
    else:
        form = AdminEditarUsuarioForm(instance=usuario_detalle)

    tickets_qs = Ticket.objects.filter(
        id_usuario=usuario_detalle
    ).select_related("id_vehiculo").order_by("-fecha", "-id")
    
    page_obj, pagination_query = paginate_queryset(request, tickets_qs)

    return render(request, "reservas/usuarios/detalle_usuario.html", {
        "usuario_detalle": usuario_detalle,
        "form": form,
        "tickets": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_tickets": page_obj.paginator.count,
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
    
    return render(request, "reservas/usuarios/admin_crear_usuario.html", {
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
        HttpResponse: Plantilla 'reservas/usuarios/usuarios_rechazados.html' con:
            - rechazados: QuerySet de usuarios rechazados.
            - usuario: Instancia del usuario logueado (admin).
    """
    rechazados_qs = Usuario.objects.filter(rechazado=True).select_related("id_cargo")
    page_obj, pagination_query = paginate_queryset(request, rechazados_qs)

    return render(request, "reservas/usuarios/usuarios_rechazados.html", {
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
        HttpResponse: Plantilla 'reservas/tickets/monitor_activos.html' con:
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

    return render(request, "reservas/tickets/monitor_activos.html", {
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
    import csv
    from django.http import HttpResponse
    
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

# ══════════════════════════════════════════════════════════════════════════════
# ÉPICA 6: ABM (ALTA, BAJA, MODIFICACIÓN) DE VEHÍCULOS
# ══════════════════════════════════════════════════════════════════════════════
# HU 6.1: Listado de vehículos
# HU 6.2: Alta de vehículo
# HU 6.3: Edición / baja de vehículo


@login_requerido
@admin_requerido
def listado_vehiculos(request):
    """
    Vista del listado de vehículos de los vehículos (HU 6.1).

    Muestra todos los vehículos (activos e inactivos) ordenados
    por marca y modelo. Desde aquí se puede navegar a crear o editar.

    Args:
        request (HttpRequest): Objeto de solicitud (GET).

    Returns:
        HttpResponse: Plantilla 'reservas/vehiculos/listado_vehiculos.html' con:
            - vehiculos: QuerySet de todos los vehículos.
            - usuario: Instancia del usuario logueado (admin).
    """
    vehiculos_decano = Vehiculo.objects.filter(exclusivo_decanato=True).order_by("marca", "modelo")
    vehiculos_qs = Vehiculo.objects.filter(exclusivo_decanato=False).order_by("marca", "modelo")
    page_obj, pagination_query = paginate_queryset(request, vehiculos_qs)

    return render(request, "reservas/vehiculos/listado_vehiculos.html", {
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
        HttpResponse: Plantilla 'reservas/vehiculos/form_vehiculo.html' con:
            - form: VehiculoForm.
            - titulo: "Agregar vehículo".
            - usuario: Instancia del usuario logueado (admin).

    Redirección (POST exitoso):
        - Redirect a listado_vehiculos.

    Messages (POST):
        - success: "Vehículo agregado a los vehículos."
    """
    if request.method == "POST":
        form = VehiculoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Vehículo agregado a los vehículos.")
            return redirect("listado_vehiculos")
    else:
        form = VehiculoForm()
    return render(request, "reservas/vehiculos/form_vehiculo.html", {
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
        HttpResponse: Plantilla 'reservas/vehiculos/form_vehiculo.html' con:
            - form: VehiculoForm pre-poblado.
            - titulo: "Editar vehículo: {marca} {modelo}".
            - vehiculo: Instancia del vehículo.
            - usuario: Instancia del usuario logueado (admin).

    Redirección (POST exitoso):
        - Redirect a listado_vehiculos.

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
            return redirect("listado_vehiculos")
    else:
        form = VehiculoForm(instance=vehiculo)
    return render(request, "reservas/vehiculos/form_vehiculo.html", {
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
    from django.db.models import Count, Sum
    import json
    from .utils.chart_utils import generar_grafico_barras_horizontal, generar_grafico_torta

    from django.db.models.functions import TruncMonth
    from django.utils import timezone
    from datetime import timedelta

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
    from django.db.models import Sum as _Sum
    dist_est_agg  = tickets_periodo.aggregate(total=_Sum("distancia_est"))["total"]
    dist_real_agg = tickets_periodo.filter(distancia_real__isnull=False).aggregate(total=_Sum("distancia_real"))["total"]
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
    from django.db.models import Sum as _Sum
    from django.db.models.functions import TruncMonth
    from django.utils import timezone
    from datetime import timedelta

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
    dist_est_agg  = base_qs.aggregate(total=_Sum("distancia_est"))["total"]
    dist_real_agg = base_qs.filter(distancia_real__isnull=False).aggregate(total=_Sum("distancia_real"))["total"]
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
    from django.db.models import Count as _Count
    top_usuarios_veh = (
        base_qs.values("id_usuario__nombre", "id_usuario__apellido", "id_usuario__id_cargo__nombre")
        .annotate(total=_Count("id"))
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
    import io
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from django.utils import timezone
    from django.db.models import Count
    from django.db.models.functions import TruncMonth
    from datetime import timedelta
    from weasyprint import HTML
    from django.db.models import Sum
    from .utils.chart_utils import generar_grafico_barras_horizontal, generar_grafico_torta
    

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
        HttpResponse: Plantilla 'reservas/auth/verificar_correo.html' con:
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

    return render(request, "reservas/auth/verificar_correo.html", {
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
    from .utils.password_recovery import crear_recuperacion, enviar_correo_recuperacion

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

    return render(request, "reservas/auth/solicitar_recuperacion.html", {"form": form})


def verificar_recuperacion(request):
    from .forms import VerificarRecuperacionForm
    from .utils.password_recovery import verificar_recuperacion_por_codigo, crear_recuperacion, enviar_correo_recuperacion
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

    return render(request, "reservas/auth/verificar_recuperacion.html", {
        "form": form,
        "correo": usuario.correo,
        "segundos_restantes": segundos_restantes,
    })


def verificar_recuperacion_enlace(request, token):
    from .utils.password_recovery import verificar_recuperacion_por_token

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
    from .utils.password_recovery import consumir_recuperacion

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

    return render(request, "reservas/auth/nueva_contrasena.html", {"form": form})


@login_requerido
def api_calcular_distancia(request):
    """
    API endpoint para calcular la distancia desde UTN FRRE al destino dado.
    """
    from .utils.services import calcular_distancia_y_tiempo_osrm
    destino = request.GET.get("q", "")
    if not destino:
        return JsonResponse({"distancia_est": 0.0, "duracion_segundos": 0.0})
        
    km, duracion = calcular_distancia_y_tiempo_osrm(destino)
    return JsonResponse({"distancia_est": km, "duracion_segundos": duracion})

# ══════════════════════════════════════════════════════════════════════════════
# Configuración Global
# ══════════════════════════════════════════════════════════════════════════════

@login_requerido
@admin_requerido
def configuracion_global(request):
    """
    Vista para administrar las configuraciones globales del sistema.
    Permite modificar días de anticipación y gestionar los feriados.
    """
    usuario = get_usuario_sesion(request)
    config = ConfiguracionGlobal.get_solo()
    
    if request.method == "POST":
        action = request.POST.get("action")
        
        if action == "add_feriado":
            fecha_str = request.POST.get("fecha_feriado")
            descripcion = request.POST.get("descripcion_feriado", "").strip()
            if fecha_str:
                try:
                    fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                    if not Feriado.objects.filter(fecha=fecha).exists():
                        Feriado.objects.create(fecha=fecha, descripcion=descripcion)
                        messages.success(request, f"Feriado del {fecha.strftime('%d/%m/%Y')} agregado correctamente.")
                    else:
                        messages.error(request, "Ya existe un feriado en esa fecha.")
                except ValueError:
                    messages.error(request, "Formato de fecha inválido.")
            else:
                messages.error(request, "La fecha es requerida.")
            return redirect("configuracion_global")
            
        elif action == "delete_feriado":
            feriado_id = request.POST.get("feriado_id")
            if feriado_id:
                Feriado.objects.filter(pk=feriado_id).delete()
                messages.success(request, "Feriado eliminado.")
            return redirect("configuracion_global")
            
        elif action == "upload_csv_feriados":
            csv_file = request.FILES.get("csv_feriados")
            if not csv_file:
                messages.error(request, "Debe seleccionar un archivo CSV.")
            elif not csv_file.name.endswith('.csv'):
                messages.error(request, "El archivo debe tener extensión .csv.")
            else:
                try:
                    import csv
                    from io import StringIO
                    decoded_file = csv_file.read().decode('utf-8', errors='ignore')
                    reader = csv.reader(StringIO(decoded_file), delimiter=',')
                    agregados = 0
                    repetidos = 0
                    errores = 0
                    for index, row in enumerate(reader):
                        # Asume formato: YYYY-MM-DD, Descripcion
                        if index == 0 and ("fecha" in str(row).lower() or "date" in str(row).lower()):
                            continue # saltar encabezado
                        if len(row) >= 1:
                            try:
                                fecha_str = row[0].strip()
                                if not fecha_str: continue
                                desc = row[1].strip() if len(row) > 1 else ""
                                fecha_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                                feriado, created = Feriado.objects.get_or_create(
                                    fecha=fecha_obj,
                                    defaults={'descripcion': desc}
                                )
                                if created:
                                    agregados += 1
                                else:
                                    repetidos += 1
                            except ValueError:
                                errores += 1
                    
                    if agregados > 0 and repetidos == 0:
                        msg = f"Se importaron {agregados} feriados exitosamente."
                        if errores > 0: msg += f" ({errores} errores de formato)."
                        messages.success(request, msg)
                    elif agregados > 0 and repetidos > 0:
                        msg = f"Se agregaron {agregados} fecha(s) nueva(s) correctamente, pero {repetidos} fecha(s) fue(ron) ignorada(s) porque ya estaba(n) registrada(s)."
                        if errores > 0: msg += f" ({errores} errores de formato)."
                        messages.warning(request, msg)
                    elif agregados == 0 and repetidos > 0:
                        msg = f"No se agregaron fechas nuevas. Las fechas del archivo ya estaban registradas."
                        if errores > 0: msg += f" ({errores} errores de formato)."
                        messages.error(request, msg)
                    else:
                        msg = "No se encontraron fechas válidas en el archivo CSV."
                        if errores > 0: msg += f" ({errores} filas ignoradas por error de formato)."
                        messages.error(request, msg)
                except Exception as e:
                    messages.error(request, f"Error al procesar el archivo CSV: {str(e)}")
            return redirect("configuracion_global")

        elif action == "sync_feriados":
            try:
                import holidays
                anio = date.today().year
                
                # Se agregan los de Argentina en general, y los de Chaco ('H')
                ar_holidays = holidays.AR(subdiv='H', years=anio)
                agregados = 0
                repetidos = 0
                for dt, name in ar_holidays.items():
                    feriado, created = Feriado.objects.get_or_create(
                        fecha=dt,
                        defaults={'descripcion': name}
                    )
                    if created:
                        agregados += 1
                    else:
                        repetidos += 1
                
                if agregados > 0 and repetidos == 0:
                    messages.success(request, f"Se sincronizaron los feriados del año {anio} exitosamente. Se agregaron {agregados} feriados nuevos.")
                elif agregados > 0 and repetidos > 0:
                    messages.warning(request, f"Se agregaron {agregados} feriados nuevos del {anio}, pero {repetidos} ya estaban registrados.")
                elif agregados == 0 and repetidos > 0:
                    messages.error(request, f"No se agregaron feriados nuevos del {anio}. Todos ya estaban registrados en el sistema.")
                else:
                    messages.error(request, f"No se encontraron feriados para el año {anio}.")
            except Exception as e:
                messages.error(request, f"Error al sincronizar feriados: {str(e)}")
            return redirect("configuracion_global")
            
        else:
            form = ConfiguracionGlobalForm(request.POST, instance=config)
            if form.is_valid():
                form.save()
                messages.success(request, "La configuración se actualizó correctamente.")
                return redirect("configuracion_global")
    else:
        form = ConfiguracionGlobalForm(instance=config)
        
    feriados = Feriado.objects.filter(fecha__year__gte=date.today().year).order_by("fecha")
        
    return render(request, "reservas/admin/configuracion.html", {
        "form": form,
        "usuario": usuario,
        "feriados": feriados,
    })


# ══════════════════════════════════════════════════════════════════════════════
# UTILIDAD DE DESARROLLO: Previsualizador de Emails
# ══════════════════════════════════════════════════════════════════════════════
from django.conf import settings

def preview_email(request, template_name):
    """
    Vista de desarrollo para renderizar y visualizar plantillas de correo en el navegador.
    Solo disponible si DEBUG es True (para seguridad en producción).
    """
    if not settings.DEBUG:
        from django.http import Http404
        raise Http404("Preview no disponible en producción.")

    from django.utils import timezone
    from datetime import timedelta

    class MockUser:
        nombre = "Juan"
        apellido = "Pérez"
        correo = "juan.perez@example.com"
        dni = "12345678"
        legajo = "L-999"

    class MockVehiculo:
        marca = "Toyota"
        modelo = "Corolla"
        patente = "AB 123 CD"

    class MockTicket:
        pk = 4059
        id_usuario = MockUser()
        id_vehiculo = MockVehiculo()
        destino = "Facultad de Ingeniería - UTN"
        hora_inicio = timezone.now()
        hora_fin = timezone.now() + timedelta(hours=3)
        observacion = "Este es un texto de ejemplo de una observación."
        distancia_est = 45.5
        cant_pasajeros = 3

    context = {
        "usuario": MockUser(),
        "ticket": MockTicket(),
        "url_sistema": "http://localhost:8000",
        "dias_anticipacion": 2,
        "dias_cancelacion": 1,
    }

    try:
        from django.shortcuts import render
        return render(request, f"reservas/emails/{template_name}.html", context)
    except Exception as e:
        from django.http import HttpResponse
        return HttpResponse(f"Error cargando plantilla '{template_name}': {e}", status=404)
