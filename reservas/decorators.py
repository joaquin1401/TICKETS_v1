"""
decorators.py - Decoradores reutilizables para autenticación y permisos.

Propósito:
──────
Encapsular lógica repetida de validación de permisos en decoradores.
Simplifica vistas y centraliza reglas de acceso.

Ventajas sobre duplicar código:
✓ Una línea en la vista vs 5-10 líneas en cada una
✓ Cambios en reglas de acceso se hacen en 1 lugar
✓ Más fácil de testear
✓ Compatible con Django's decorator patterns
"""

from functools import wraps
from typing import Callable, Any
from django.shortcuts import redirect
from django.contrib import messages
from django.http import HttpRequest, HttpResponse


def login_requerido(view_func: Callable) -> Callable:
    """
    Decorador que redirige al login si no hay sesión activa.
    
    Parámetros:
        view_func: Vista a proteger
    
    Retorna:
        Vista envuelta que verifica sesión
    
    Uso:
        @login_requerido
        def dashboard(request):
            ...
    
    Nota: Depende de UsuarioSessionMiddleware para que request.user esté disponible.
    """
    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not request.session.get("usuario_id"):
            return redirect("login")
        return view_func(request, *args, **kwargs)
    
    return wrapper


def admin_requerido(view_func: Callable) -> Callable:
    """
    Decorador que verifica si el usuario tiene permisos de administrador.
    
    Parámetros:
        view_func: Vista a proteger
    
    Retorna:
        Vista envuelta que verifica permisos de admin
    
    Uso:
        @login_requerido
        @admin_requerido
        def panel_admin(request):
            ...
    
    Nota: Debe usarse DESPUÉS de @login_requerido.
          La validación depende de request.es_admin (inyectado por middleware).
    
    Lógica: User es admin si su cargo tiene prioridad == 0.
    """
    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not request.session.get("es_admin"):
            messages.error(request, "No tenés permisos para acceder a esa sección.")
            return redirect("dashboard")
        return view_func(request, *args, **kwargs)
    
    return wrapper


def requiere_usuario_activo(view_func: Callable) -> Callable:
    """
    Decorador que verifica que el usuario esté aprobado y no rechazado.
    
    Parámetros:
        view_func: Vista a proteger
    
    Retorna:
        Vista envuelta que verifica estado del usuario
    
    Nota: Utiliza método puede_ingresar() del modelo Usuario.
    """
    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not request.user or not request.user.puede_ingresar():
            messages.error(request, "Tu cuenta no está activa.")
            request.session.flush()
            return redirect("login")
        return view_func(request, *args, **kwargs)
    
    return wrapper
