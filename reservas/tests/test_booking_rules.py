from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from reservas.models import Cargo, Usuario, Vehiculo, Ticket
from reservas.utils.services import crear_ticket_con_reglas, cancelar_ticket_usuario, ResultadoCreacion

def get_cargo(nombre, prioridad):
    cargo, created = Cargo.objects.get_or_create(nombre=nombre, defaults={'prioridad': prioridad})
    if not created and cargo.prioridad != prioridad:
        cargo.prioridad = prioridad
        cargo.save()
    return cargo

class TestReglasNegocioTickets(TestCase):
    def setUp(self):
        # Cargos
        self.cargo_decano = get_cargo(Cargo.DECANO, 1)
        self.cargo_secretario = get_cargo(Cargo.SECRETARIO, 2)
        self.cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        
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
            marca="Toyota", modelo="Hilux", patente="AA111AA", cant_pasajeros=4, activo=True, exclusivo_decanato=False
        )
        self.vehiculo_decanato = Vehiculo.objects.create(
            marca="Lexus", modelo="LS", patente="BB222BB", cant_pasajeros=4, activo=True, exclusivo_decanato=True
        )
        self.vehiculo_taller = Vehiculo.objects.create(
            marca="Ford", modelo="Ranger", patente="CC333CC", cant_pasajeros=4, activo=False, exclusivo_decanato=False
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
        """Cancelación permitida hasta los días de anticipación antes de la fecha."""
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


class TestReservasMultiDia(TestCase):
    def setUp(self):
        # Create necessary Cargo, Usuario, Vehiculo
        self.cargo = get_cargo(Cargo.USUARIO, 3)
        self.usuario = Usuario.objects.create(
            nombre="User", apellido="Test", correo="test@test.com", id_cargo=self.cargo, valido=True
        )
        self.vehiculo = Vehiculo.objects.create(
            marca="Toyota", modelo="Corolla", patente="DD444DD", cant_pasajeros=4, activo=True
        )

    def test_get_tickets_del_mes_multi_dia(self):
        """Prueba que get_tickets_del_mes recupere tickets que se solapan con el mes consultado."""
        from datetime import datetime
        from reservas.utils.services import get_tickets_del_mes
        
        # Reserva que empieza el mes anterior (Mayo 30) y termina este mes (Junio 2)
        ticket_anterior = Ticket.objects.create(
            id_usuario=self.usuario,
            id_vehiculo=self.vehiculo,
            hora_inicio=datetime(2026, 5, 30, 10, 0),
            hora_fin=datetime(2026, 6, 2, 18, 0),
            estado=Ticket.ESTADO_APROBADO,
            destino="Dest",
            cant_pasajeros=2
        )
        
        # Reserva que está completamente en el mes (Junio 10 al 12)
        ticket_dentro = Ticket.objects.create(
            id_usuario=self.usuario,
            id_vehiculo=self.vehiculo,
            hora_inicio=datetime(2026, 6, 10, 9, 0),
            hora_fin=datetime(2026, 6, 12, 17, 0),
            estado=Ticket.ESTADO_APROBADO,
            destino="Dest 2",
            cant_pasajeros=2
        )
        
        # Reserva que empieza en este mes (Junio 29) y termina el próximo mes (Julio 2)
        ticket_posterior = Ticket.objects.create(
            id_usuario=self.usuario,
            id_vehiculo=self.vehiculo,
            hora_inicio=datetime(2026, 6, 29, 8, 0),
            hora_fin=datetime(2026, 7, 2, 12, 0),
            estado=Ticket.ESTADO_APROBADO,
            destino="Dest 3",
            cant_pasajeros=2
        )
        
        # Obtener tickets de Junio 2026
        tickets = get_tickets_del_mes(self.vehiculo, 2026, 6)
        ticket_ids = {t.id for t in tickets}
        
        self.assertIn(ticket_anterior.id, ticket_ids)
        self.assertIn(ticket_dentro.id, ticket_ids)
        self.assertIn(ticket_posterior.id, ticket_ids)

    def test_get_tickets_del_dia_multi_dia(self):
        """Prueba que get_tickets_del_dia recupere un ticket en cualquier día del rango reservado."""
        from datetime import datetime, date
        from reservas.utils.services import get_tickets_del_dia
        
        ticket = Ticket.objects.create(
            id_usuario=self.usuario,
            id_vehiculo=self.vehiculo,
            hora_inicio=datetime(2026, 6, 10, 9, 0),
            hora_fin=datetime(2026, 6, 12, 17, 0),
            estado=Ticket.ESTADO_APROBADO,
            destino="Dest",
            cant_pasajeros=2
        )
        
        # Verificar que se recupera en el día de inicio
        tickets_dia_10 = get_tickets_del_dia(self.vehiculo, date(2026, 6, 10))
        self.assertIn(ticket, tickets_dia_10)
        
        # Verificar que se recupera en el día intermedio
        tickets_dia_11 = get_tickets_del_dia(self.vehiculo, date(2026, 6, 11))
        self.assertIn(ticket, tickets_dia_11)
        
        # Verificar que se recupera en el día de fin
        tickets_dia_12 = get_tickets_del_dia(self.vehiculo, date(2026, 6, 12))
        self.assertIn(ticket, tickets_dia_12)
        
        # Verificar que NO se recupera un día antes
        tickets_dia_9 = get_tickets_del_dia(self.vehiculo, date(2026, 6, 9))
        self.assertNotIn(ticket, tickets_dia_9)
        
        # Verificar que NO se recupera un día después
        tickets_dia_13 = get_tickets_del_dia(self.vehiculo, date(2026, 6, 13))
        self.assertNotIn(ticket, tickets_dia_13)


class TestMargenEntreReservas(TestCase):
    """Pruebas para la funcionalidad de margen configurable entre reservas (mismo vehículo)."""

    def setUp(self):
        self.cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        self.usuario = Usuario.objects.create(
            nombre="Usuario", apellido="Test", correo="usuario@test.com",
            id_cargo=self.cargo_usuario, valido=True
        )
        self.vehiculo = Vehiculo.objects.create(
            marca="Toyota", modelo="Corolla", patente="ABC123", cant_pasajeros=4, activo=True
        )
        from reservas.models import ConfiguracionGlobal
        self.config = ConfiguracionGlobal.get_solo()
        self.config.horas_margen_entre_reservas = 1
        self.config.minutos_margen_entre_reservas = 0
        self.config.save()

    def test_margen_default_1_hora_bloquea_reserva_cercana(self):
        ahora = timezone.now()
        inicio_existente = ahora + timedelta(days=10)
        fin_existente = inicio_existente + timedelta(hours=2)
        
        Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo,
            hora_inicio=inicio_existente, hora_fin=fin_existente,
            estado=Ticket.ESTADO_APROBADO, destino="X", cant_pasajeros=1
        )
        
        inicio_nuevo = fin_existente + timedelta(minutes=30)
        fin_nuevo = inicio_nuevo + timedelta(hours=2)
        
        res = crear_ticket_con_reglas(
            self.usuario, self.vehiculo, inicio_nuevo, fin_nuevo,
            destino="Y", cant_pasajeros=1
        )
        self.assertEqual(res.estado, ResultadoCreacion.BLOQUEADO)

    def test_margen_respetado_permite_reserva(self):
        ahora = timezone.now()
        inicio_existente = ahora + timedelta(days=10)
        fin_existente = inicio_existente + timedelta(hours=2)
        
        Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo,
            hora_inicio=inicio_existente, hora_fin=fin_existente,
            estado=Ticket.ESTADO_APROBADO, destino="X", cant_pasajeros=1
        )
        
        inicio_nuevo = fin_existente + timedelta(hours=1)
        fin_nuevo = inicio_nuevo + timedelta(hours=2)
        
        res = crear_ticket_con_reglas(
            self.usuario, self.vehiculo, inicio_nuevo, fin_nuevo,
            destino="Y", cant_pasajeros=1
        )
        self.assertEqual(res.estado, ResultadoCreacion.OK)

    def test_margen_configurable_2_horas(self):
        ahora = timezone.now()
        inicio_existente = ahora + timedelta(days=10)
        fin_existente = inicio_existente + timedelta(hours=2)
        
        self.config.horas_margen_entre_reservas = 2
        self.config.save()
        
        Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo,
            hora_inicio=inicio_existente, hora_fin=fin_existente,
            estado=Ticket.ESTADO_APROBADO, destino="X", cant_pasajeros=1
        )
        
        inicio_nuevo = fin_existente + timedelta(hours=1)
        fin_nuevo = inicio_nuevo + timedelta(hours=2)
        
        res = crear_ticket_con_reglas(
            self.usuario, self.vehiculo, inicio_nuevo, fin_nuevo,
            destino="Y", cant_pasajeros=1
        )
        self.assertEqual(res.estado, ResultadoCreacion.BLOQUEADO)
        
        self.config.horas_margen_entre_reservas = 1
        self.config.save()

    def test_margen_0_horas_permite_reserva_inmediata(self):
        ahora = timezone.now()
        inicio_existente = ahora + timedelta(days=10)
        fin_existente = inicio_existente + timedelta(hours=2)
        
        self.config.horas_margen_entre_reservas = 0
        self.config.save()
        
        Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo,
            hora_inicio=inicio_existente, hora_fin=fin_existente,
            estado=Ticket.ESTADO_APROBADO, destino="X", cant_pasajeros=1
        )
        
        inicio_nuevo = fin_existente
        fin_nuevo = inicio_nuevo + timedelta(hours=2)
        
        res = crear_ticket_con_reglas(
            self.usuario, self.vehiculo, inicio_nuevo, fin_nuevo,
            destino="Y", cant_pasajeros=1
        )
        self.assertEqual(res.estado, ResultadoCreacion.OK)
        
        self.config.horas_margen_entre_reservas = 1
        self.config.save()

    def test_margen_aplica_en_ambos_extremos(self):
        ahora = timezone.now()
        inicio_existente = ahora + timedelta(days=10, hours=10)
        fin_existente = inicio_existente + timedelta(hours=2)
        
        Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo,
            hora_inicio=inicio_existente, hora_fin=fin_existente,
            estado=Ticket.ESTADO_APROBADO, destino="X", cant_pasajeros=1
        )
        
        # Caso 1: termina muy cerca del inicio del existente
        inicio_nuevo_caso1 = inicio_existente - timedelta(hours=2)
        fin_nuevo_caso1 = inicio_existente - timedelta(minutes=30)
        
        res1 = crear_ticket_con_reglas(
            self.usuario, self.vehiculo, inicio_nuevo_caso1, fin_nuevo_caso1,
            destino="Y", cant_pasajeros=1
        )
        self.assertEqual(res1.estado, ResultadoCreacion.BLOQUEADO)
        
        # Caso 2: empieza muy cerca del fin del existente
        inicio_nuevo_caso2 = fin_existente + timedelta(minutes=30)
        fin_nuevo_caso2 = inicio_nuevo_caso2 + timedelta(hours=2)
        
        res2 = crear_ticket_con_reglas(
            self.usuario, self.vehiculo, inicio_nuevo_caso2, fin_nuevo_caso2,
            destino="Z", cant_pasajeros=1
        )
        self.assertEqual(res2.estado, ResultadoCreacion.BLOQUEADO)

    def test_admin_ignora_margen(self):
        """El administrador (prioridad 0) puede crear reservas sin respetar el margen."""
        from datetime import timedelta
        ahora = timezone.now()
        inicio_existente = ahora + timedelta(days=10)
        fin_existente = inicio_existente + timedelta(hours=2)
        
        # Configurar margen de 1 hora
        self.config.horas_margen_entre_reservas = 1
        self.config.save()
        
        # Crear ticket existente
        Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo,
            hora_inicio=inicio_existente, hora_fin=fin_existente,
            estado=Ticket.ESTADO_APROBADO, destino="X", cant_pasajeros=1
        )
        
        # Admin intenta crear ticket inmediatamente después (viola el margen)
        inicio_nuevo = fin_existente + timedelta(minutes=10)  # Solo 10 min de diferencia
        fin_nuevo = inicio_nuevo + timedelta(hours=2)
        
        # Crear admin
        cargo_admin = get_cargo(Cargo.ADMIN_SEU, 0)
        admin = Usuario.objects.create(
            nombre="Admin", apellido="Sistema", correo="admin@test.com",
            id_cargo=cargo_admin, valido=True
        )
        
        res = crear_ticket_con_reglas(
            admin, self.vehiculo, inicio_nuevo, fin_nuevo,
            destino="Y", cant_pasajeros=1
        )
        # El admin debe poder crear el ticket a pesar de violar el margen
        self.assertEqual(res.estado, ResultadoCreacion.OK)
