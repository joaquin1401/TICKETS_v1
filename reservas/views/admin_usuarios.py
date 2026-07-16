"""
Vistas de gestión administrativa de usuarios.

Épica 5 (usuarios):
    - HU 1.3/1.4: panel_validacion() — aprobación y rechazo de usuarios.
    - HU 5.1: usuarios() — directorio de usuarios con filtros.
    - detalle_usuario() — detalle y edición de un usuario.
    - admin_crear_usuario() — creación directa de usuario por admin.
    - HU 5.2: usuarios_rechazados() — listado de usuarios rechazados.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from ..models import Usuario, Ticket
from ..forms import FiltroUsuariosForm, AdminCrearUsuarioForm, AdminEditarUsuarioForm
from django.db.models import Q
from ._base import get_usuario_sesion, paginate_queryset, login_requerido, admin_requerido


# ══════════════════════════════════════════════════════════════════════════════
# ÉPICA 5: GESTIÓN Y SUPERVISIÓN ADMINISTRATIVA — USUARIOS
# ══════════════════════════════════════════════════════════════════════════════


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
                mensaje = (  # default por si falla el html
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
    usuarios_qs = Usuario.objects.exclude(valido=False, rechazado=False).select_related("id_cargo")

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
            usuarios_qs = usuarios_qs.filter(q_objects)
        if cargo:
            usuarios_qs = usuarios_qs.filter(id_cargo=cargo)

    page_obj, pagination_query = paginate_queryset(request, usuarios_qs)

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
