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
from django.utils import timezone
from datetime import timedelta
from .models import Cargo, Usuario, Vehiculo, Ticket
from .services import crear_ticket_con_reglas, cancelar_ticket_usuario, ResultadoCreacion

class TestReglasNegocioTickets(TestCase):
    def setUp(self):
        # Cargos
        self.cargo_decano = Cargo.objects.create(nombre=Cargo.DECANO, prioridad=1)
        self.cargo_secretario = Cargo.objects.create(nombre=Cargo.SECRETARIO, prioridad=2)
        self.cargo_usuario = Cargo.objects.create(nombre=Cargo.USUARIO, prioridad=3)
        
        # Usuarios
        self.decano = Usuario.objects.create(
            nombre="Decano", apellido="1", correo="decano@test.com", id_cargo=self.cargo_decano, valido=True
        )
        self.secretario = Usuario.objects.create(
            nombre="Secretario", apellido="1", correo="secretario@test.com", id_cargo=self.cargo_secretario, valido=True
        )
        self.usuario_comun = Usuario.objects.create(
            nombre="Usuario", apellido="1", correo="usuario@test.com", id_cargo=self.cargo_usuario, valido=True
        )
        
        # Vehículos
        self.vehiculo_normal = Vehiculo.objects.create(
            marca="Toyota", modelo="Hilux", cant_pasajeros=4, activo=True, exclusivo_decanato=False
        )
        self.vehiculo_decanato = Vehiculo.objects.create(
            marca="Lexus", modelo="LS", cant_pasajeros=4, activo=True, exclusivo_decanato=True
        )
        self.vehiculo_taller = Vehiculo.objects.create(
            marca="Ford", modelo="Ranger", cant_pasajeros=4, activo=False, exclusivo_decanato=False
        )

        self.ahora = timezone.now()

    def test_decano_prioridad_sobre_vehiculo_decanato(self):
        """Un usuario normal no puede reservar el vehículo exclusivo, el Decano sí."""
        inicio = self.ahora + timedelta(days=10)
        fin = inicio + timedelta(hours=2)
        
        # Falla para el Secretario
        res_sec = crear_ticket_con_reglas(self.secretario, self.vehiculo_decanato, inicio, fin, destino="X", cant_pasajeros=1)
        self.assertEqual(res_sec.estado, ResultadoCreacion.BLOQUEADO)
        
        # Exito para el Decano
        res_decano = crear_ticket_con_reglas(self.decano, self.vehiculo_decanato, inicio, fin, destino="X", cant_pasajeros=1)
        self.assertEqual(res_decano.estado, ResultadoCreacion.OK)

    def test_decano_sobrescribe_reserva_normal(self):
        """El Decano tiene prioridad 1 y puede sobrescribir reservas de prioridad 2 o 3."""
        inicio = self.ahora + timedelta(days=10)
        fin = inicio + timedelta(hours=2)
        
        # Usuario reserva vehículo normal
        crear_ticket_con_reglas(self.usuario_comun, self.vehiculo_normal, inicio, fin, destino="X", cant_pasajeros=1)
        self.assertTrue(Ticket.objects.filter(id_usuario=self.usuario_comun, estado=Ticket.ESTADO_APROBADO).exists())
        
        # Decano sobrescribe
        res_decano = crear_ticket_con_reglas(self.decano, self.vehiculo_normal, inicio, fin, destino="Y", cant_pasajeros=1)
        self.assertEqual(res_decano.estado, ResultadoCreacion.SOBRESCRITO)
        
        # El ticket del usuario debe estar cancelado
        self.assertTrue(Ticket.objects.filter(id_usuario=self.usuario_comun, estado=Ticket.ESTADO_CANCELADO).exists())
        self.assertTrue(Ticket.objects.filter(id_usuario=self.decano, estado=Ticket.ESTADO_APROBADO).exists())

    def test_vehiculo_en_mantenimiento(self):
        """No permitir pedidos si el vehículo está inactivo/mantenimiento."""
        inicio = self.ahora + timedelta(days=10)
        fin = inicio + timedelta(hours=2)
        
        res = crear_ticket_con_reglas(self.usuario_comun, self.vehiculo_taller, inicio, fin, destino="X", cant_pasajeros=1)
        self.assertEqual(res.estado, ResultadoCreacion.BLOQUEADO)

    def test_limite_2_meses(self):
        """No permitir reservas con más de 2 meses (60 días) de antelación."""
        inicio = self.ahora + timedelta(days=61)
        fin = inicio + timedelta(hours=2)
        
        res = crear_ticket_con_reglas(self.usuario_comun, self.vehiculo_normal, inicio, fin, destino="X", cant_pasajeros=1)
        self.assertEqual(res.estado, ResultadoCreacion.BLOQUEADO)
        
        inicio_valido = self.ahora + timedelta(days=59)
        res_valido = crear_ticket_con_reglas(self.usuario_comun, self.vehiculo_normal, inicio_valido, inicio_valido + timedelta(hours=2), destino="X", cant_pasajeros=1)
        self.assertEqual(res_valido.estado, ResultadoCreacion.OK)

    def test_minimo_3_dias(self):
        """Bloqueo 3 días antes para crear reservas."""
        inicio = self.ahora + timedelta(days=2)
        fin = inicio + timedelta(hours=2)
        
        res = crear_ticket_con_reglas(self.usuario_comun, self.vehiculo_normal, inicio, fin, destino="X", cant_pasajeros=1)
        self.assertEqual(res.estado, ResultadoCreacion.BLOQUEADO)
        
        inicio_valido = self.ahora + timedelta(days=4)
        res_valido = crear_ticket_con_reglas(self.usuario_comun, self.vehiculo_normal, inicio_valido, inicio_valido + timedelta(hours=2), destino="X", cant_pasajeros=1)
        self.assertEqual(res_valido.estado, ResultadoCreacion.OK)

    def test_cancelacion_5_dias(self):
        """Cancelación permitida hasta 5 días antes de la fecha."""
        # Setup tickets
        inicio_lejos = self.ahora + timedelta(days=10)
        inicio_cerca = self.ahora + timedelta(days=4)
        
        res_lejos = crear_ticket_con_reglas(self.usuario_comun, self.vehiculo_normal, inicio_lejos, inicio_lejos + timedelta(hours=2), destino="X", cant_pasajeros=1)
        t_lejos = res_lejos.ticket
        
        # Simulamos que lo creó hace tiempo cambiando la fecha directo en BD porque el servicio de creación bloquea a 3 días
        t_cerca = Ticket.objects.create(
            id_usuario=self.usuario_comun, id_vehiculo=self.vehiculo_normal,
            hora_inicio=inicio_cerca, hora_fin=inicio_cerca + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO, destino="X", cant_pasajeros=1
        )
        
        # Test 1: Intenta cancelar el lejano (10 días) -> EXITO
        exito_lejos, msg = cancelar_ticket_usuario(t_lejos, self.usuario_comun)
        self.assertTrue(exito_lejos)
        t_lejos.refresh_from_db()
        self.assertEqual(t_lejos.estado, Ticket.ESTADO_CANCELADO)
        
        # Test 2: Intenta cancelar el cercano (4 días) -> FALLO
        exito_cerca, msg = cancelar_ticket_usuario(t_cerca, self.usuario_comun)
        self.assertFalse(exito_cerca)
        t_cerca.refresh_from_db()
        self.assertEqual(t_cerca.estado, Ticket.ESTADO_APROBADO)

    def test_usuario_menor_jerarquia_no_sobrescribe(self):
        """Un usuario de menor jerarquía (ej. Usuario, prioridad 3) no puede sobrescribir a uno de mayor (ej. Decano, prioridad 1)."""
        inicio = self.ahora + timedelta(days=10)
        fin = inicio + timedelta(hours=2)
        
        # Decano reserva primero
        crear_ticket_con_reglas(self.decano, self.vehiculo_normal, inicio, fin, destino="X", cant_pasajeros=1)
        
        # Usuario intenta sobrescribir
        res = crear_ticket_con_reglas(self.usuario_comun, self.vehiculo_normal, inicio, fin, destino="Y", cant_pasajeros=1)
        self.assertEqual(res.estado, ResultadoCreacion.BLOQUEADO)

    def test_usuario_misma_jerarquia_no_sobrescribe(self):
        """Un usuario no puede sobrescribir una reserva de otro con la misma jerarquía."""
        inicio = self.ahora + timedelta(days=10)
        fin = inicio + timedelta(hours=2)
        
        # Secretario reserva primero
        crear_ticket_con_reglas(self.secretario, self.vehiculo_normal, inicio, fin, destino="X", cant_pasajeros=1)
        
        # Otro usuario con jerarquía Secretario intenta sobrescribir
        secretario2 = Usuario.objects.create(
            nombre="Sec2", apellido="2", correo="sec2@test.com", id_cargo=self.cargo_secretario, valido=True
        )
        res = crear_ticket_con_reglas(secretario2, self.vehiculo_normal, inicio, fin, destino="Y", cant_pasajeros=1)
        self.assertEqual(res.estado, ResultadoCreacion.BLOQUEADO)

    def test_creacion_exitosa_sin_conflictos(self):
        """Creación de un ticket sin conflictos debería retornar OK y guardar los datos correctamente."""
        inicio = self.ahora + timedelta(days=10)
        fin = inicio + timedelta(hours=2)
        
        res = crear_ticket_con_reglas(
            self.usuario_comun, 
            self.vehiculo_normal, 
            inicio, 
            fin, 
            destino="Centro de la ciudad", 
            cant_pasajeros=2,
            descripcion="Viaje de prueba"
        )
        
        self.assertEqual(res.estado, ResultadoCreacion.OK)
        self.assertIsNotNone(res.ticket)
        self.assertEqual(res.ticket.estado, Ticket.ESTADO_APROBADO)
        self.assertEqual(res.ticket.destino, "Centro de la ciudad")
        self.assertEqual(res.ticket.cant_pasajeros, 2)
        self.assertEqual(res.ticket.descripcion, "Viaje de prueba")

    def test_capacidad_vehiculo_excedida(self):
        """No se permite crear una reserva si la cantidad de pasajeros solicitada supera la capacidad del vehículo."""
        inicio = self.ahora + timedelta(days=10)
        fin = inicio + timedelta(hours=2)
        
        res = crear_ticket_con_reglas(
            self.usuario_comun, 
            self.vehiculo_normal, 
            inicio, 
            fin, 
            destino="Sede Central", 
            cant_pasajeros=5  # vehiculo_normal tiene cant_pasajeros=4 en setUp
        )
        self.assertEqual(res.estado, ResultadoCreacion.BLOQUEADO)
        self.assertIn("excede la capacidad", res.mensaje)
