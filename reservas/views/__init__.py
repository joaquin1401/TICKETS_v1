"""
Paquete de vistas de la aplicación reservas.

Re-exporta todas las vistas para mantener compatibilidad con urls.py
sin necesidad de refactorizar el enrutamiento existente.
"""

from ._base import *
from .admin_tickets import *
from .admin_usuarios import *
from .analiticas import *
from .auth import *
from .choferes import *
from .email_auth import *
from .misc import *
from .tickets import *
from .vehiculos import *
