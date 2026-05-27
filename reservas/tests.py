"""
Test suite para la aplicación de reservas.

Define casos de prueba unitarios e integración para validar:
- Modelos (Cargo, Usuario, Vehículo, Ticket).
- Servicios (detección de conflictos, resolución jerárquica).
- Vistas (autenticación, creación de tickets, administración).
- Formularios (validaciones, limpieza de datos).

Estructura recomendada:
- TestCasosModelos: Pruebas de lógica de modelos (save, properties).
- TestCasosServicios: Pruebas de la lógica de negocio (HU 4.1 a 4.3).
- TestCasosVistas: Pruebas de flujos HTTP y autorización.
- TestCasosFormularios: Pruebas de validación de formularios.

Ejecución:
    python manage.py test reservas
    python manage.py test reservas.tests.TestCasosServicios -v 2
"""

from django.test import TestCase

