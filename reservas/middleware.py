"""
middleware.py - Middleware personalizado para inyectar usuario en request.

Patrón de Arquitectura:
────────────────────
En lugar de llamar get_usuario_sesion(request) en cada vista (DRY violation),
usamos middleware para inyectar el usuario en request.user automáticamente.

Beneficios:
✓ No repetimos lógica de obtención de usuario
✓ request.user disponible en todas las vistas, templates y servicios
✓ Facilita testing (mockear request.user es trivial)
✓ Aleja la lógica de sesión de las vistas
"""

from typing import Optional
from django.utils.deprecation import MiddlewareMixin
from .models import Usuario


class UsuarioSessionMiddleware(MiddlewareMixin):
    """
    Middleware que carga el usuario desde la sesión e inyecta en request.
    
    Después de este middleware:
        request.user → Instancia de Usuario (con cargo precargado) o None
        request.es_admin → bool indicando si es administrador
    
    Nota: En Django estándar, request.user es el usuario de autenticación.
          Aquí lo sobrescribimos para usar nuestro Usuario custom.
          Considerar migrar a AbstractBaseUser en futuro para usar Django's auth.
    """
    
    def process_request(self, request) -> Optional[any]:
        """
        Ejecutado antes de cada vista.
        
        Proceso:
        1. Obtiene usuario_id de request.session
        2. Busca Usuario en BD (con select_related)
        3. Inyecta en request.user
        4. Inyecta flag de admin en request.es_admin
        """
        usuario_id = request.session.get("usuario_id")
        
        if usuario_id:
            try:
                # select_related para evitar N+1 cuando se acceda a id_cargo
                request.user = (
                    Usuario.objects
                    .select_related("id_cargo")
                    .get(pk=usuario_id)
                )
                request.es_admin = request.user.es_admin
            except Usuario.DoesNotExist:
                # Usuario fue eliminado, limpiar sesión
                request.session.flush()
                request.user = None
                request.es_admin = False
        else:
            request.user = None
            request.es_admin = False
        
        return None  # No intercepta la respuesta
