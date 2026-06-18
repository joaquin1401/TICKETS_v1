"""
Paquete de la aplicación Django 'reservas'.

Sistema de gestión de reservas de vehículos corporativos con lógica de
prioridad jerárquica y resolución automática de conflictos.

Módulos principales:
    - models.py: Definición de entidades (Cargo, Usuario, Vehículo, Ticket).
    - views.py: Vistas tradicionales con templates (HTML).
    - services.py: Motor de reglas de negocio (colisiones, jerarquía).
    - forms.py: Formularios de validación de datos.
    - admin.py: Configuración de Django Admin.
    - urls.py: Enrutamiento HTTP.
    - apps.py: Configuración de la aplicación.

Estructura del proyecto:
    - templates/: Plantillas HTML (vistas tradicionales).
    - management/: Comandos custom de Django (migraciones, seeders).
    - migrations/: Historial de cambios de esquema BD.
    - fixtures/: Datos de prueba para seeding.

Épicas funcionales:
    1. Autenticación (registro, login, validación por admin).
    2. Inicio y gestión de tickets (usuario normal).
    3. Calendario interactivo e integración temporal.
    4. Reglas de negocio (colisiones, prioridad jerárquica).
    5. Supervisión administrativa (directorio, auditoría, monitor).
    6. ABM de vehículos (alta, baja, modificación de vehículos).

Convención de sesión:
    - request.session["usuario_id"]: PK del usuario logueado.
    - request.session["es_admin"]: bool (True si cargo.prioridad == 0).
"""
