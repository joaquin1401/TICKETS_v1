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
    @admin_requerido: Redirige a dashboard si no es administrador.
"""

import calendar
from datetime import date, timedelta

from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q

from .models import Usuario, Vehiculo, Ticket, Cargo
from .forms import (
    RegistroForm, LoginForm, TicketForm, VehiculoSelectorForm,
    FiltroUsuariosForm, VehiculoForm,
    VerificacionCodigoForm,          # [NUEVO] formulario de código de 6 dígitos
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
    registra un mensaje de error y redirige al dashboard.

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
            return redirect("dashboard")
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
        HttpResponse: Redirige a dashboard tras login exitoso,
            o re-renderiza formulario con errores.

    Validaciones:
        1. Si usuario logueado: redirige a dashboard.
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

            # [NUEVO] Verificación de correo: bloquear login si el usuario
            # completó el registro pero todavía no verificó su email.
            # Aplica solo si el campo correo_verificado existe en el modelo
            # (requiere haber corrido la migración correspondiente).
            if hasattr(usuario, 'correo_verificado') and not usuario.correo_verificado:
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
            return redirect("dashboard")
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
# ÉPICA 2: DASHBOARD Y TICKETS (USUARIO NORMAL)
# ══════════════════════════════════════════════════════════════════════════════
# HU 2.1: Dashboard con formulario rápido de reserva
# HU 2.2: Historial de tickets
# HU 2.3: Detalle de ticket


@login_requerido
def dashboard(request):
    """
    Vista de dashboard principal del usuario (HU 2.1).

    Muestra un formulario rápido para crear reservas y listado de
    los 5 tickets más recientes del usuario. Aplica lógica de conflictos
    y jerarquía mediante services.crear_ticket_con_reglas().

    Args:
        request (HttpRequest): Objeto de solicitud.
            - GET: Muestra dashboard con formulario vacío.
            - POST: Procesa creación de ticket.

    Returns:
        HttpResponse: Plantilla 'reservas/dashboard.html' con:
            - form: TicketForm (vacío o con errores).
            - usuario: Instancia del usuario logueado.
            - tickets_recientes: Últimos 5 tickets del usuario.

    POST (crear ticket):
        1. Valida TicketForm.clean() (horas, coincidencia contraseñas, etc).
        2. Si hora_fin no especificada, asigna hora_inicio + 2 horas (default).
        3. Llama crear_ticket_con_reglas() que aplica lógica de conflictos.
        4. Según ResultadoCreacion.estado:
            - OK: success message, redirige a historial.
            - SOBRESCRITO: warning message, redirige a historial.
            - BLOQUEADO: error message, re-renderiza dashboard.

    Messages:
        - success: "Reserva creada exitosamente."
        - warning: "Reserva creada. Se cancelaron reservas de... por jerarquía."
        - error: Mensaje específico de bloqueo por conflicto.

    Optimizaciones BD:
        - .select_related("id_vehiculo") para tickets recientes.
        - get_usuario_sesion() pre-carga id_cargo.
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
    tickets_qs = Ticket.objects.filter(
        id_usuario=usuario
    ).select_related("id_vehiculo").order_by("-hora_inicio")
    page_obj, pagination_query = paginate_queryset(request, tickets_qs)

    return render(request, "reservas/historial.html", {
        "tickets": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_tickets": page_obj.paginator.count,
        "usuario": usuario,
    })


@login_requerido
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

    return render(request, "reservas/detalle_ticket.html", {
        "ticket": ticket,
        "usuario": usuario,
    })


# ══════════════════════════════════════════════════════════════════════════════
# ÉPICA 3: CALENDARIO INTERACTIVO
# ══════════════════════════════════════════════════════════════════════════════
# HU 3.1: Selector de vehículo
# HU 3.2: Vista mensual del calendario
# HU 3.3: Línea de tiempo horaria


@login_requerido
def calendario(request):
    """
    Vista del calendario interactivo (HU 3.1, 3.2).

    Permite seleccionar un vehículo y ver su disponibilidad mensual.
    Marca días con reservas aprobadas. Proporciona navegación entre meses.

    Args:
        request (HttpRequest): Objeto de solicitud.
            - GET: Recibe parámetros ?vehiculo=X&anio=Y&mes=Z
            - POST: No utilizado (GET form).

    Returns:
        HttpResponse: Plantilla 'reservas/calendario.html' con:
            - form: VehiculoSelectorForm.
            - vehiculo: Vehículo seleccionado (None si no válido).
            - cal: Matriz de semanas (calendar.monthcalendar).
            - nombre_mes: Nombre legible del mes (ej: "Diciembre 2024").
            - anio, mes: Valores de navegación.
            - dias_con_reservas: Set de date con tickets aprobados.
            - mes_anterior, mes_siguiente: Tuplas (anio, mes) para links.
            - usuario: Instancia del usuario logueado.

    Lógica:
        1. GET ?vehiculo=X: Valida formulario y carga tickets del mes.
        2. Si formulario válido: dias_con_reservas = {ticket.hora_inicio.date()}.
        3. Genera matriz de calendario y tuplas de navegación.

    Notas:
        - Navega a mes anterior/siguiente considerando bordes de año.
        - Utiliza calendar.monthcalendar() del módulo estándar.
        - Los días sin reservas no tienen restricción visual (diseño en template).
    """
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
    """
    Vista de línea de tiempo horaria de un día específico (HU 3.3).

    Muestra ocupación horaria de un vehículo en un día determinado.
    Útil para visualizar conflictos y rangos disponibles.

    Args:
        request (HttpRequest): Objeto de solicitud (GET).
        vehiculo_id (int): PK del vehículo.
        anio (int): Año (YYYY).
        mes (int): Mes (1-12).
        dia (int): Día (1-31).

    Returns:
        HttpResponse: Plantilla 'reservas/timeline_dia.html' con:
            - vehiculo: Instancia de vehículo.
            - fecha: date(anio, mes, dia).
            - tickets: QuerySet de tickets aprobados ese día.
            - usuario: Instancia del usuario logueado.
            - horas: Lista de strings ["06", "07", ..., "22"] para template.

    Raises:
        Http404: Si el vehículo no existe o está inactivo.

    Notas:
        - Rango de horas: 6:00 a 22:59 (16 horas de trabajo).
        - Template itera sobre horas y tickets para mostrar ocupación.
    """
    usuario = get_usuario_sesion(request)
    vehiculo = get_object_or_404(Vehiculo, pk=vehiculo_id, activo=True)
    fecha = date(anio, mes, dia)
    tickets_qs = get_tickets_del_dia(vehiculo, fecha)
    page_obj, pagination_query = paginate_queryset(request, tickets_qs)
    horas = ["06", "07", "08", "09", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22"]

    return render(request, "reservas/timeline_dia.html", {
        "vehiculo": vehiculo,
        "fecha": fecha,
        "tickets": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_tickets": page_obj.paginator.count,
        "usuario": usuario,
        "horas": horas,
    })


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
            messages.warning(request, f"{usuario_objetivo.nombre_completo} fue rechazado.")

        return redirect("panel_validacion")

    return render(request, "reservas/panel_validacion.html", {
        "pendientes": pendientes,
        "usuario": get_usuario_sesion(request),
    })


@login_requerido
@admin_requerido
def directorio_usuarios(request):
    """
    Vista del directorio de usuarios con búsqueda y filtros (HU 5.1).

    Muestra lista de usuarios aprobados (valido=True). Permite buscar
    por nombre/apellido/correo y filtrar por cargo.

    Args:
        request (HttpRequest): Objeto de solicitud (GET).
            Parámetros:
            - busqueda (str): Busca en nombre, apellido, correo (icontains).
            - cargo (int): PK de cargo para filtrar.

    Returns:
        HttpResponse: Plantilla 'reservas/directorio_usuarios.html' con:
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

    return render(request, "reservas/directorio_usuarios.html", {
        "form": form,
        "usuarios": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_usuarios": page_obj.paginator.count,
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
    tickets_qs = Ticket.objects.filter(
        estado=Ticket.ESTADO_APROBADO,
        hora_inicio__gte=date.today(),
    ).select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo").order_by("hora_inicio")

    page_obj, pagination_query = paginate_queryset(request, tickets_qs)
    vehiculos_en_uso = tickets_qs.values("id_vehiculo").distinct().count()

    return render(request, "reservas/monitor_activos.html", {
        "tickets": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_tickets": page_obj.paginator.count,
        "vehiculos_en_uso": vehiculos_en_uso,
        "usuario": get_usuario_sesion(request),
    })


@login_requerido
@admin_requerido
def auditoria_tickets(request):
    """
    Vista de auditoría de tickets históricos y cancelados (HU 5.4).

    Muestra todos los tickets con estado CANCELADO o con hora_inicio < hoy.
    Útil para análisis de patrones, conflictos resueltos y cancelaciones.

    Args:
        request (HttpRequest): Objeto de solicitud (GET).

    Returns:
        HttpResponse: Plantilla 'reservas/auditoria.html' con:
            - tickets: QuerySet de tickets históricos/cancelados.
            - usuario: Instancia del usuario logueado (admin).

    Criterios:
        - estado == CANCELADO (por sobrescritura o admin), O
        - hora_inicio < hoy (pasados).

    Notas:
        - Campo observacion permite revisar razones de cancelación.
        - Ordenados por hora_inicio descendente (más recientes primero).
    """
    tickets_qs = Ticket.objects.filter(
        Q(estado=Ticket.ESTADO_CANCELADO) | Q(hora_inicio__lt=date.today())
    ).select_related("id_usuario", "id_vehiculo", "id_usuario__id_cargo").order_by("-hora_inicio")

    page_obj, pagination_query = paginate_queryset(request, tickets_qs)

    return render(request, "reservas/auditoria.html", {
        "tickets": page_obj.object_list,
        "page_obj": page_obj,
        "pagination_query": pagination_query,
        "total_tickets": page_obj.paginator.count,
        "usuario": get_usuario_sesion(request),
    })


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
    vehiculos_qs = Vehiculo.objects.all().order_by("marca", "modelo")
    page_obj, pagination_query = paginate_queryset(request, vehiculos_qs)

    return render(request, "reservas/listado_flota.html", {
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

    return render(request, "reservas/verificar_correo.html", {
        "form": form,
        "correo": usuario.correo,
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
