"""
Helpers, decoradores y constantes compartidos por todas las vistas.

Centraliza:
    - Constante ITEMS_PER_PAGE
    - get_usuario_sesion(): obtiene el usuario desde la sesión.
    - paginate_queryset(): paginación reutilizable.
    - Decoradores: @login_requerido, @admin_requerido,
                   @chofer_requerido, @sin_chofer_requerido
    - custom_404(): manejador de error 404.
"""

from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from django.contrib import messages

from ..models import Usuario, Cargo


ITEMS_PER_PAGE = 20


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
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


# ══════════════════════════════════════════════════════════════════════════════
# DECORADORES DE AUTORIZACIÓN
# ══════════════════════════════════════════════════════════════════════════════

def login_requerido(view_func):
    """
    Decorador que redirige a login si no hay sesión activa o el usuario fue eliminado.

    Valida que request.session["usuario_id"] exista y que el usuario siga en la BD.
    Si no, limpia la sesión y redirige a la ruta 'login'.
    """
    def wrapper(request, *args, **kwargs):
        if not request.session.get("usuario_id"):
            return redirect("login")
        usuario = get_usuario_sesion(request)
        if not usuario:
            request.session.flush()
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


# ══════════════════════════════════════════════════════════════════════════════
# MANEJADORES DE ERROR
# ══════════════════════════════════════════════════════════════════════════════

def custom_404(request, exception=None):
    """
    Manejador personalizado para el error 404.
    Muestra una página indicando que la ruta no existe.
    """
    return render(request, "reservas/404.html", status=404)
