"""
Paquete de vistas de la aplicación reservas.

Re-exporta todas las vistas para mantener compatibilidad con urls.py
sin necesidad de refactorizar el enrutamiento existente.
"""

from ._base import *
from .auth import *
from .email_auth import *
from .tickets import *
from .choferes import *
from .admin_usuarios import *
from .admin_tickets import *
from .vehiculos import *
from .analiticas import *
from .misc import *
