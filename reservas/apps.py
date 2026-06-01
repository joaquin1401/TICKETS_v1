"""
Configuración de la aplicación Django 'reservas'.

Define la clase AppConfig que Django utiliza para registrar e inicializar
la aplicación en el proyecto. Incluye configuración de modelo automático
y metadatos de la aplicación.
"""

from django.apps import AppConfig


class ReservasConfig(AppConfig):
    """
    Configuración de la aplicación 'reservas'.

    Atributos:
        default_auto_field (str): Campo de clave primaria automático para modelos.
            Utiliza BigAutoField (ID de 64 bits) para soportar escala en BD.
        name (str): Nombre del módulo de la aplicación en el proyecto.

    Notas:
        Esta clase debe registrarse en settings.INSTALLED_APPS del proyecto.
        El patrón moderno de Django prefiere BigAutoField sobre AutoField.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reservas'
    def ready(self):
        # Import signals to ensure they are registered when app is ready
        try:
            import reservas.signals  # noqa: F401
        except Exception:
            # Avoid breaking startup if signals fail during migrations
            pass
