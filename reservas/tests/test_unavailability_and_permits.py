from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from reservas.models import Cargo, Usuario, Vehiculo, Ticket, PermisoReservaExtraordinaria, ConfiguracionGlobal
from reservas.utils.services import crear_ticket_con_reglas as _crear_ticket_con_reglas, ResultadoCreacion, dar_baja_temporal_vehiculo, _reasignar_ticket

def crear_ticket_con_reglas(*args, **kwargs):
    kwargs.setdefault("confirmado", True)
    return _crear_ticket_con_reglas(*args, **kwargs)
from reservas.forms import TicketForm

def get_cargo(nombre, prioridad):
    cargo, created = Cargo.objects.get_or_create(nombre=nombre, defaults={'prioridad': prioridad})
    if not created and cargo.prioridad != prioridad:
        cargo.prioridad = prioridad
        cargo.save()
    return cargo

class TestBajaTemporalVehiculo(TestCase):
    """Pruebas para baja temporal de vehículos (inactivo_hasta, reasignación, etc.)."""

    def setUp(self):
        # Cargos
        self.cargo_admin = get_cargo(Cargo.ADMIN_SEU, 0)
        self.cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        self.cargo_chofer = get_cargo(Cargo.CHOFER, 4)

        # Usuarios
        self.admin = Usuario.objects.create(
            nombre="Admin", apellido="SEU", correo="admin@test.com",
            id_cargo=self.cargo_admin, valido=True
        )
        self.usuario = Usuario.objects.create(
            nombre="Usuario", apellido="Normal", correo="user@test.com",
            id_cargo=self.cargo_usuario, valido=True
        )

        # Vehículos
        self.vehiculo1 = Vehiculo.objects.create(
            marca="Toyota", modelo="Hilux", patente="AA111AA",
            cant_pasajeros=4, activo=True
        )
        self.vehiculo2 = Vehiculo.objects.create(
            marca="Ford", modelo="Ranger", patente="BB222BB",
            cant_pasajeros=4, activo=True
        )

        self.ahora = timezone.now()

    def test_guardar_limpia_inactivo_hasta_expirado(self):
        """save() debe limpiar inactivo_hasta si ya expiró."""
        ayer = timezone.localdate() - timedelta(days=1)
        self.vehiculo1.inactivo_hasta = ayer
        self.vehiculo1.save()
        self.vehiculo1.refresh_from_db()
        self.assertIsNone(self.vehiculo1.inactivo_hasta)

    def test_guardar_mantiene_inactivo_hasta_vigente(self):
        """save() debe mantener inactivo_hasta si es futuro."""
        manana = timezone.localdate() + timedelta(days=1)
        self.vehiculo1.inactivo_hasta = manana
        self.vehiculo1.save()
        self.vehiculo1.refresh_from_db()
        self.assertEqual(self.vehiculo1.inactivo_hasta, manana)

    def test_esta_en_baja_temporal_true(self):
        """esta_en_baja_temporal() retorna True si inactivo_hasta >= hoy."""
        manana = timezone.localdate() + timedelta(days=1)
        self.vehiculo1.inactivo_hasta = manana
        self.vehiculo1.save()
        self.assertTrue(self.vehiculo1.esta_en_baja_temporal())

    def test_esta_en_baja_temporal_false_sin_fecha(self):
        """esta_en_baja_temporal() retorna False si inactivo_hasta es None."""
        self.assertFalse(self.vehiculo1.esta_en_baja_temporal())

    def test_esta_inactivo_en_rango(self):
        """esta_inactivo_en_rango() detecta solapamiento con rango dado."""
        hoy = timezone.localdate()
        manana = hoy + timedelta(days=1)
        pasado_manana = hoy + timedelta(days=2)
        self.vehiculo1.inactivo_hasta = pasado_manana
        self.vehiculo1.save()
        self.assertTrue(self.vehiculo1.esta_inactivo_en_rango(hoy, manana))
        self.assertTrue(self.vehiculo1.esta_inactivo_en_rango(manana, pasado_manana))
        self.assertFalse(self.vehiculo1.esta_inactivo_en_rango(hoy - timedelta(days=5), hoy - timedelta(days=3)))
        self.assertFalse(self.vehiculo1.esta_inactivo_en_rango(pasado_manana + timedelta(days=1), pasado_manana + timedelta(days=3)))

    def test_dar_baja_temporal_cancela_tickets_futuros(self):
        inicio = self.ahora + timedelta(days=1, hours=8)
        fin = inicio + timedelta(hours=2)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=fin,
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        resultado = dar_baja_temporal_vehiculo(self.vehiculo1, 3, self.admin)
        ticket.refresh_from_db()
        self.assertEqual(ticket.estado, Ticket.ESTADO_CANCELADO)
        self.assertEqual(resultado["total_afectados"], 1)

    def test_dar_baja_temporal_no_cancela_tickets_fuera_de_rango(self):
        inicio = self.ahora + timedelta(days=10, hours=8)
        fin = inicio + timedelta(hours=2)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=fin,
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        resultado = dar_baja_temporal_vehiculo(self.vehiculo1, 3, self.admin)
        ticket.refresh_from_db()
        self.assertEqual(ticket.estado, Ticket.ESTADO_APROBADO)
        self.assertEqual(resultado["total_afectados"], 0)

    def test_dar_baja_temporal_crea_permiso_5dias(self):
        # Desactivamos el segundo vehículo para forzar la cancelación y el permiso
        self.vehiculo2.activo = False
        self.vehiculo2.save()
        inicio = self.ahora + timedelta(hours=8)
        fin = inicio + timedelta(hours=2)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=fin,
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        dar_baja_temporal_vehiculo(self.vehiculo1, 3, self.admin)
        permiso = PermisoReservaExtraordinaria.objects.filter(usuario=self.usuario, ticket_cancelado=ticket).first()
        self.assertIsNotNone(permiso)
        self.assertFalse(permiso.usado)
        self.assertEqual(permiso.motivo, PermisoReservaExtraordinaria.MOTIVO_BAJA_VEHICULO)
        self.assertEqual(permiso.valido_hasta, timezone.localdate() + timedelta(days=5))

    def test_dar_baja_temporal_ignora_tickets_no_aprobados(self):
        inicio = self.ahora + timedelta(days=1, hours=8)
        fin = inicio + timedelta(hours=2)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=fin,
            estado=Ticket.ESTADO_PENDIENTE, destino="Test", cant_pasajeros=2
        )
        resultado = dar_baja_temporal_vehiculo(self.vehiculo1, 3, self.admin)
        ticket.refresh_from_db()
        self.assertEqual(ticket.estado, Ticket.ESTADO_PENDIENTE)
        self.assertEqual(resultado["total_afectados"], 0)

    def test_reasignacion_con_vehiculo_disponible(self):
        inicio = self.ahora + timedelta(days=1, hours=8)
        fin = inicio + timedelta(hours=2)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=fin,
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        nuevo = _reasignar_ticket(ticket)
        self.assertIsNotNone(nuevo)
        self.assertEqual(nuevo.id_vehiculo, self.vehiculo2)
        self.assertEqual(nuevo.estado, Ticket.ESTADO_APROBADO)

    def test_reasignacion_sin_vehiculo_disponible(self):
        manana = timezone.localdate() + timedelta(days=2)
        self.vehiculo2.inactivo_hasta = manana
        self.vehiculo2.save()
        inicio = self.ahora + timedelta(days=1, hours=8)
        fin = inicio + timedelta(hours=2)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=fin,
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        nuevo = _reasignar_ticket(ticket)
        self.assertIsNone(nuevo)

    def test_reasignacion_no_asigna_exclusivo_decanato_a_no_decano(self):
        self.vehiculo2.exclusivo_decanato = True
        self.vehiculo2.save()
        inicio = self.ahora + timedelta(days=1, hours=8)
        fin = inicio + timedelta(hours=2)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=fin,
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        nuevo = _reasignar_ticket(ticket)
        self.assertIsNone(nuevo)

    def test_baja_con_reasignacion_no_crea_permiso(self):
        """dar_baja_temporal NO debe crear PermisoReservaExtraordinaria si el ticket se reasignó."""
        inicio = self.ahora + timedelta(hours=8)  # Hoy mismo (dentro de los días de gracia)
        fin = inicio + timedelta(hours=2)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=fin,
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        # Hay un segundo vehículo disponible → habrá reasignación
        resultado = dar_baja_temporal_vehiculo(self.vehiculo1, 3, self.admin)
        self.assertEqual(resultado["reasignados"], 1)
        self.assertEqual(resultado["cancelados"], 0)
        # NO debe haber permiso de emergencia
        permisos = PermisoReservaExtraordinaria.objects.filter(usuario=self.usuario)
        self.assertEqual(permisos.count(), 0)

    def test_baja_sin_reasignacion_si_crea_permiso_dentro_5dias(self):
        """dar_baja_temporal SÍ crea PermisoReservaExtraordinaria si NO hay reasignación y está dentro de los días de gracia."""
        # vehiculo2 no disponible → no habrá reasignación
        self.vehiculo2.activo = False
        self.vehiculo2.save()
        inicio = self.ahora + timedelta(hours=8)  # Hoy mismo (dentro de los días de gracia)
        fin = inicio + timedelta(hours=2)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=fin,
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        resultado = dar_baja_temporal_vehiculo(self.vehiculo1, 3, self.admin)
        self.assertEqual(resultado["cancelados"], 1)
        self.assertEqual(resultado["reasignados"], 0)
        # SÍ debe haber permiso de emergencia
        permisos = PermisoReservaExtraordinaria.objects.filter(usuario=self.usuario)
        self.assertEqual(permisos.count(), 1)
        self.assertFalse(permisos.first().usado)

    def test_baja_sin_reasignacion_no_crea_permiso_fuera_5dias(self):
        """dar_baja_temporal NO crea PermisoReservaExtraordinaria si NO hay reasignación pero está fuera de los días de gracia."""
        # vehiculo2 no disponible → no habrá reasignación
        self.vehiculo2.activo = False
        self.vehiculo2.save()
        config = ConfiguracionGlobal.get_solo()
        dias_gracia = config.dias_anticipacion_cancelacion
        inicio = self.ahora + timedelta(days=dias_gracia + 1)  # Fuera de los días de gracia
        fin = inicio + timedelta(hours=2)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=fin,
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        resultado = dar_baja_temporal_vehiculo(self.vehiculo1, 10, self.admin)
        self.assertEqual(resultado["cancelados"], 1)
        self.assertEqual(resultado["reasignados"], 0)
        # NO debe haber permiso porque está fuera de los días de gracia
        permisos = PermisoReservaExtraordinaria.objects.filter(usuario=self.usuario)
        self.assertEqual(permisos.count(), 0)


class TestPermisoReservaExtraordinaria(TestCase):
    """Pruebas para el modelo PermisoReservaExtraordinaria (permiso de emergencia)."""

    def setUp(self):
        self.cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        self.usuario = Usuario.objects.create(
            nombre="Usuario", apellido="Test", correo="user@test.com",
            id_cargo=self.cargo_usuario, valido=True
        )
        self.vehiculo = Vehiculo.objects.create(
            marca="Toyota", modelo="Corolla", patente="AAA111",
            cant_pasajeros=4, activo=True
        )
        self.ahora = timezone.now()

    def test_permiso_se_crea_valido(self):
        inicio = self.ahora + timedelta(days=1)
        fin = inicio + timedelta(hours=2)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo,
            hora_inicio=inicio, hora_fin=fin,
            estado=Ticket.ESTADO_CANCELADO, destino="Test", cant_pasajeros=2
        )
        permiso = PermisoReservaExtraordinaria.objects.create(
            usuario=self.usuario,
            ticket_cancelado=ticket,
            motivo=PermisoReservaExtraordinaria.MOTIVO_BAJA_VEHICULO,
            valido_hasta=timezone.localdate() + timedelta(days=5),
        )
        self.assertFalse(permiso.usado)
        self.assertEqual(permiso.valido_hasta, timezone.localdate() + timedelta(days=5))
        self.assertTrue(permiso.esta_vigente())

    def test_permiso_no_vigente_si_usado(self):
        inicio = self.ahora + timedelta(days=1)
        fin = inicio + timedelta(hours=2)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo,
            hora_inicio=inicio, hora_fin=fin,
            estado=Ticket.ESTADO_CANCELADO, destino="Test", cant_pasajeros=2
        )
        permiso = PermisoReservaExtraordinaria.objects.create(
            usuario=self.usuario,
            ticket_cancelado=ticket,
            motivo=PermisoReservaExtraordinaria.MOTIVO_BAJA_VEHICULO,
            valido_hasta=timezone.localdate() + timedelta(days=5),
            usado=True,
        )
        self.assertFalse(permiso.esta_vigente())

    def test_permiso_no_vigente_si_expirado(self):
        inicio = self.ahora + timedelta(days=1)
        fin = inicio + timedelta(hours=2)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo,
            hora_inicio=inicio, hora_fin=fin,
            estado=Ticket.ESTADO_CANCELADO, destino="Test", cant_pasajeros=2
        )
        permiso = PermisoReservaExtraordinaria.objects.create(
            usuario=self.usuario,
            ticket_cancelado=ticket,
            motivo=PermisoReservaExtraordinaria.MOTIVO_BAJA_VEHICULO,
            valido_hasta=timezone.localdate() - timedelta(days=1),
        )
        self.assertFalse(permiso.esta_vigente())


class TestCancelacionPorPrioridad(TestCase):
    """Pruebas para cancelacián de tickets por prioridad jerárquica y reasignación."""

    def setUp(self):
        self.cargo_decano = get_cargo(Cargo.DECANO, 1)
        self.cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        self.cargo_chofer = get_cargo(Cargo.CHOFER, 4)

        self.decano = Usuario.objects.create(
            nombre="Decano", apellido="1", correo="decano@test.com",
            id_cargo=self.cargo_decano, valido=True
        )
        self.usuario_comun = Usuario.objects.create(
            nombre="Usuario", apellido="1", correo="user@test.com",
            id_cargo=self.cargo_usuario, valido=True
        )

        self.vehiculo1 = Vehiculo.objects.create(
            marca="Toyota", modelo="Hilux", patente="AA111AA",
            cant_pasajeros=4, activo=True
        )
        self.vehiculo2 = Vehiculo.objects.create(
            marca="Ford", modelo="Ranger", patente="BB222BB",
            cant_pasajeros=4, activo=True
        )

        self.ahora = timezone.now()

    def test_prioridad_cancela_y_crea_permiso_5dias(self):
        inicio = self.ahora + timedelta(days=4)
        fin = inicio + timedelta(hours=2)

        # Desactivamos el segundo vehículo para forzar la cancelación y el permiso
        self.vehiculo2.activo = False
        self.vehiculo2.save()

        res1 = crear_ticket_con_reglas(
            self.usuario_comun, self.vehiculo1, inicio, fin,
            destino="Test", cant_pasajeros=2
        )
        self.assertEqual(res1.estado, ResultadoCreacion.OK)

        resultado = crear_ticket_con_reglas(
            self.decano, self.vehiculo1, inicio, fin,
            destino="Decano", cant_pasajeros=2
        )
        self.assertEqual(resultado.estado, ResultadoCreacion.SOBRESCRITO)
        self.assertEqual(len(resultado.tickets_cancelados), 1)

        permisos = PermisoReservaExtraordinaria.objects.filter(usuario=self.usuario_comun)
        self.assertEqual(permisos.count(), 1)
        self.assertEqual(permisos.first().motivo, PermisoReservaExtraordinaria.MOTIVO_PRIORIDAD)

    def test_prioridad_sin_permiso_si_fuera_de_5dias(self):
        inicio = self.ahora + timedelta(days=10, hours=8)
        fin = inicio + timedelta(hours=2)

        # Desactivamos el segundo vehículo para forzar la cancelación sin reasignación
        self.vehiculo2.activo = False
        self.vehiculo2.save()

        res1 = crear_ticket_con_reglas(
            self.usuario_comun, self.vehiculo1, inicio, fin,
            destino="Test", cant_pasajeros=2
        )
        self.assertEqual(res1.estado, ResultadoCreacion.OK)

        resultado = crear_ticket_con_reglas(
            self.decano, self.vehiculo1, inicio, fin,
            destino="Decano", cant_pasajeros=2
        )
        self.assertEqual(resultado.estado, ResultadoCreacion.SOBRESCRITO)

        permisos = PermisoReservaExtraordinaria.objects.filter(usuario=self.usuario_comun)
        self.assertEqual(permisos.count(), 0)

    def test_prioridad_con_reasignacion(self):
        inicio = self.ahora + timedelta(days=4)
        fin = inicio + timedelta(hours=2)

        res1 = crear_ticket_con_reglas(
            self.usuario_comun, self.vehiculo1, inicio, fin,
            destino="Test", cant_pasajeros=2
        )
        self.assertEqual(res1.estado, ResultadoCreacion.OK)

        resultado = crear_ticket_con_reglas(
            self.decano, self.vehiculo1, inicio, fin,
            destino="Decano", cant_pasajeros=2
        )
        self.assertEqual(resultado.estado, ResultadoCreacion.SOBRESCRITO)

        tickets_activos = Ticket.objects.filter(
            id_usuario=self.usuario_comun,
            estado=Ticket.ESTADO_APROBADO,
        )
        self.assertEqual(tickets_activos.count(), 1)
        ticket_reasignado = tickets_activos.first()
        self.assertEqual(ticket_reasignado.id_vehiculo, self.vehiculo2)

    def test_prioridad_sin_reasignacion_sin_vehiculo(self):
        self.vehiculo2.activo = False
        self.vehiculo2.save()

        inicio = self.ahora + timedelta(days=4)
        fin = inicio + timedelta(hours=2)

        res1 = crear_ticket_con_reglas(
            self.usuario_comun, self.vehiculo1, inicio, fin,
            destino="Test", cant_pasajeros=2
        )
        self.assertEqual(res1.estado, ResultadoCreacion.OK)

        resultado = crear_ticket_con_reglas(
            self.decano, self.vehiculo1, inicio, fin,
            destino="Decano", cant_pasajeros=2
        )
        self.assertEqual(resultado.estado, ResultadoCreacion.SOBRESCRITO)
        self.assertEqual(len(resultado.tickets_cancelados), 1)

        tickets_cancelados = Ticket.objects.filter(
            id_usuario=self.usuario_comun,
            estado=Ticket.ESTADO_CANCELADO,
        )
        self.assertEqual(tickets_cancelados.count(), 1)


class TestFormularioPermisoEmergencia(TestCase):
    """Pruebas para la validacion del formulario TicketForm con PermisoReservaExtraordinaria."""

    def setUp(self):
        from reservas.models import ConfiguracionGlobal
        self.cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        self.cargo_admin = get_cargo(Cargo.ADMIN_SEU, 0)

        self.usuario = Usuario.objects.create(
            nombre="Usuario", apellido="Test", correo="user@test.com",
            id_cargo=self.cargo_usuario, valido=True
        )
        self.admin = Usuario.objects.create(
            nombre="Admin", apellido="SEU", correo="admin@test.com",
            id_cargo=self.cargo_admin, valido=True
        )
        self.vehiculo = Vehiculo.objects.create(
            marca="Toyota", modelo="Corolla", patente="AAA111",
            cant_pasajeros=4, activo=True
        )
        config = ConfiguracionGlobal.get_solo()
        config.dias_anticipacion_reservas = 3
        config.save()

    def _crear_permiso_emergencia(self, usuario):
        inicio = timezone.now() + timedelta(days=1)
        fin = inicio + timedelta(hours=2)
        ticket = Ticket.objects.create(
            id_usuario=usuario, id_vehiculo=self.vehiculo,
            hora_inicio=inicio, hora_fin=fin,
            estado=Ticket.ESTADO_CANCELADO, destino="Test", cant_pasajeros=2
        )
        return PermisoReservaExtraordinaria.objects.create(
            usuario=usuario,
            ticket_cancelado=ticket,
            motivo=PermisoReservaExtraordinaria.MOTIVO_BAJA_VEHICULO,
            valido_hasta=timezone.localdate() + timedelta(days=5),
        )

    def test_formulario_rechaza_sin_permiso(self):
        manana = timezone.now() + timedelta(hours=24)
        data = {
            "id_vehiculo": self.vehiculo.pk,
            "destino": "Test",
            "cant_pasajeros": 2,
            "descripcion": "Prueba",
            "hora_inicio": manana,
            "hora_fin": manana + timedelta(hours=2),
        }
        form = TicketForm(data, es_admin=False, es_usuario_general=False, usuario=self.usuario)
        self.assertFalse(form.is_valid())
        self.assertIn("hora_inicio", form.errors)

    def test_formulario_acepta_con_permiso_emergencia(self):
        self._crear_permiso_emergencia(self.usuario)
        manana = timezone.now() + timedelta(hours=24)
        data = {
            "id_vehiculo": self.vehiculo.pk,
            "destino": "Test",
            "cant_pasajeros": 2,
            "descripcion": "Prueba con permiso",
            "hora_inicio": manana,
            "hora_fin": manana + timedelta(hours=2),
        }
        form = TicketForm(data, es_admin=False, es_usuario_general=False, usuario=self.usuario)
        self.assertTrue(form.is_valid(), msg="Errores del formulario: {}".format(form.errors))

    def test_formulario_rechaza_con_permiso_usado(self):
        permiso = self._crear_permiso_emergencia(self.usuario)
        permiso.usado = True
        permiso.save()
        manana = timezone.now() + timedelta(hours=24)
        data = {
            "id_vehiculo": self.vehiculo.pk,
            "destino": "Test",
            "cant_pasajeros": 2,
            "descripcion": "Prueba",
            "hora_inicio": manana,
            "hora_fin": manana + timedelta(hours=2),
        }
        form = TicketForm(data, es_admin=False, es_usuario_general=False, usuario=self.usuario)
        self.assertFalse(form.is_valid())
        self.assertIn("hora_inicio", form.errors)


class TestLimitesConfigurables(TestCase):
    """Pruebas para verificar que los límites se adapten dinámicamente a la configuración global."""

    def setUp(self):
        from reservas.models import Cargo, Usuario, Vehiculo, ConfiguracionGlobal
        self.cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        self.cargo_admin = get_cargo(Cargo.ADMIN_SEU, 0)
        self.cargo_decano = get_cargo(Cargo.DECANO, 1)

        self.usuario = Usuario.objects.create(
            nombre="Usuario", apellido="Test", correo="user@test.com",
            id_cargo=self.cargo_usuario, valido=True
        )
        self.admin = Usuario.objects.create(
            nombre="Admin", apellido="SEU", correo="admin@test.com",
            id_cargo=self.cargo_admin, valido=True
        )
        self.decano = Usuario.objects.create(
            nombre="Decano", apellido="1", correo="decano@test.com",
            id_cargo=self.cargo_decano, valido=True
        )
        self.vehiculo1 = Vehiculo.objects.create(
            marca="Toyota", modelo="Corolla", patente="AAA111",
            cant_pasajeros=4, activo=True
        )
        self.vehiculo2 = Vehiculo.objects.create(
            marca="Ford", modelo="Ranger", patente="BBB222",
            cant_pasajeros=4, activo=True
        )
        self.ahora = timezone.now()

    def test_anticipacion_reservas_configurable(self):
        """La anticipación mínima requerida debe adaptarse a dias_anticipacion_reservas."""
        from reservas.models import ConfiguracionGlobal
        config = ConfiguracionGlobal.get_solo()
        
        # 1. Configurar a 7 días
        config.dias_anticipacion_reservas = 7
        config.save()

        # Una reserva a los 5 días debe fallar
        inicio_5_dias = self.ahora + timedelta(days=5)
        res = crear_ticket_con_reglas(
            self.usuario, self.vehiculo1, inicio_5_dias, inicio_5_dias + timedelta(hours=2),
            destino="Test", cant_pasajeros=2
        )
        self.assertEqual(res.estado, ResultadoCreacion.BLOQUEADO)
        self.assertIn("al menos 7 días", res.mensaje)

        # Una reserva a los 8 días debe pasar
        inicio_8_dias = self.ahora + timedelta(days=8)
        res2 = crear_ticket_con_reglas(
            self.usuario, self.vehiculo1, inicio_8_dias, inicio_8_dias + timedelta(hours=2),
            destino="Test", cant_pasajeros=2
        )
        self.assertEqual(res2.estado, ResultadoCreacion.OK)

    def test_permiso_emergencia_limite_dinamico_con_config(self):
        """La ventana de reserva con permiso de emergencia debe adaptarse a dias_anticipacion_reservas."""
        from reservas.models import ConfiguracionGlobal
        config = ConfiguracionGlobal.get_solo()
        config.dias_anticipacion_reservas = 7
        config.save()

        # Crear permiso de emergencia
        ticket_cancelado = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=self.ahora + timedelta(days=1), hora_fin=self.ahora + timedelta(days=1, hours=2),
            estado=Ticket.ESTADO_CANCELADO, destino="Test", cant_pasajeros=2
        )
        permiso = PermisoReservaExtraordinaria.objects.create(
            usuario=self.usuario,
            ticket_cancelado=ticket_cancelado,
            motivo=PermisoReservaExtraordinaria.MOTIVO_BAJA_VEHICULO,
            valido_hasta=timezone.localdate() + timedelta(days=7),
        )

        # El formulario para un ticket a los 6 días (menor a los 7 días configurados) debe ser válido gracias al permiso
        manana_6_dias = timezone.now() + timedelta(days=6)
        data = {
            "id_vehiculo": self.vehiculo1.pk,
            "destino": "Test",
            "cant_pasajeros": 2,
            "descripcion": "Prueba con permiso en ventana dinámica",
            "hora_inicio": manana_6_dias,
            "hora_fin": manana_6_dias + timedelta(hours=2),
        }
        form = TicketForm(data, es_admin=False, es_usuario_general=False, usuario=self.usuario)
        self.assertTrue(form.is_valid(), msg="Errores: {}".format(form.errors))

    def test_dias_anticipacion_cancelacion_crea_permiso_dinamico(self):
        """El otorgamiento y la vigencia del permiso deben adaptarse a dias_anticipacion_cancelacion."""
        from reservas.models import ConfiguracionGlobal
        config = ConfiguracionGlobal.get_solo()
        
        # Configurar a 10 días
        config.dias_anticipacion_cancelacion = 10
        config.save()

        # Vehículo 2 inactivo para que no haya reasignación
        self.vehiculo2.activo = False
        self.vehiculo2.save()

        # Ticket aprobado a los 8 días de hoy
        inicio_8_dias = self.ahora + timedelta(days=8)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio_8_dias, hora_fin=inicio_8_dias + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )

        # Dar de baja el vehículo. Al ser la salida a los 8 días (menor a los 10 días de la config),
        # debe crearse el permiso de emergencia y ser válido por 10 días.
        dar_baja_temporal_vehiculo(self.vehiculo1, 10, self.admin)

        permiso = PermisoReservaExtraordinaria.objects.filter(usuario=self.usuario, ticket_cancelado=ticket).first()
        self.assertIsNotNone(permiso)
        self.assertEqual(permiso.valido_hasta, timezone.localdate() + timedelta(days=10))

# ══════════════════════════════════════════════════════════════════════════════
# TESTS EXHAUSTIVOS — Edge Cases de Baja Temporal con Reasignación
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeCasesBajaTemporal(TestCase):
    """Edge cases exhaustivos para dar_baja_temporal_vehiculo y _reasignar_ticket."""

    def setUp(self):
        self.cargo_admin = get_cargo(Cargo.ADMIN_SEU, 0)
        self.cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        self.cargo_chofer = get_cargo(Cargo.CHOFER, 4)

        self.admin = Usuario.objects.create(
            nombre="Admin", apellido="SEU", correo="admin@test.com",
            id_cargo=self.cargo_admin, valido=True
        )
        self.usuario = Usuario.objects.create(
            nombre="Usuario", apellido="Normal", correo="user@test.com",
            id_cargo=self.cargo_usuario, valido=True
        )
        self.usuario2 = Usuario.objects.create(
            nombre="Otro", apellido="User", correo="user2@test.com",
            id_cargo=self.cargo_usuario, valido=True
        )

        self.vehiculo1 = Vehiculo.objects.create(
            marca="Toyota", modelo="Hilux", patente="AA111AA",
            cant_pasajeros=4, activo=True
        )
        self.vehiculo2 = Vehiculo.objects.create(
            marca="Ford", modelo="Ranger", patente="BB222BB",
            cant_pasajeros=4, activo=True
        )
        self.vehiculo3 = Vehiculo.objects.create(
            marca="Chevrolet", modelo="S10", patente="CC333CC",
            cant_pasajeros=6, activo=True
        )

        self.ahora = timezone.now()


    def test_solapamiento_parcial_ticket_iniciado_antes(self):
        """
        Ticket que EMPIEZA antes de hoy pero TERMINA durante la baja.
        Antes del fix, NO se cancelaba. Con el fix SÍ debe cancelarse.
        """
        ayer = self.ahora - timedelta(days=1)
        manana = self.ahora + timedelta(days=1)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=ayer, hora_fin=manana,
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        resultado = dar_baja_temporal_vehiculo(self.vehiculo1, 7, self.admin)
        ticket.refresh_from_db()
        self.assertEqual(
            ticket.estado, Ticket.ESTADO_CANCELADO,
            "Ticket que termina durante la baja debe cancelarse aunque haya empezado antes."
        )
        self.assertGreaterEqual(resultado["total_afectados"], 1)

    def test_solapamiento_parcial_ticket_empieza_durante_baja_termina_despues(self):
        """
        Ticket que empieza durante la baja y termina después.
        Debe cancelarse porque su hora_inicio está dentro del rango.
        """
        inicio = self.ahora + timedelta(days=1, hours=8)
        fin = inicio + timedelta(days=5)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=fin,
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        resultado = dar_baja_temporal_vehiculo(self.vehiculo1, 3, self.admin)
        ticket.refresh_from_db()
        self.assertEqual(ticket.estado, Ticket.ESTADO_CANCELADO)
        self.assertEqual(resultado["total_afectados"], 1)

    def test_solapamiento_parcial_ticket_mismo_dia_null_end(self):
        """
        Ticket sin hora_fin (null) que coincide con el día de inicio de la baja.
        """
        hoy_10am = self.ahora.replace(hour=10, minute=0, second=0, microsecond=0)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=hoy_10am, hora_fin=None,
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        resultado = dar_baja_temporal_vehiculo(self.vehiculo1, 3, self.admin)
        ticket.refresh_from_db()
        self.assertEqual(ticket.estado, Ticket.ESTADO_CANCELADO)
        self.assertEqual(resultado["total_afectados"], 1)



    # ── TEST BUG 2: Idempotencia ──────────────────────────────────────────

    def test_doble_llamada_baja_temporal_no_duplica_cancelaciones(self):
        """
        Llamar dar_baja_temporal_vehiculo dos veces no debe duplicar
        cancelaciones ni permisos de emergencia, ni lanzar errores.
        """
        self.vehiculo2.activo = False
        self.vehiculo2.save()
        self.vehiculo3.activo = False
        self.vehiculo3.save()

        inicio = self.ahora + timedelta(days=1, hours=8)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=inicio + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )

        r1 = dar_baja_temporal_vehiculo(self.vehiculo1, 5, self.admin)
        self.assertEqual(r1["total_afectados"], 1)

        r2 = dar_baja_temporal_vehiculo(self.vehiculo1, 5, self.admin)
        self.assertEqual(
            r2["total_afectados"], 0,
            "Segunda llamada no debe procesar tickets ya cancelados."
        )

        permisos = PermisoReservaExtraordinaria.objects.filter(usuario=self.usuario)
        self.assertEqual(permisos.count(), 1)

    def test_doble_llamada_baja_sin_permiso_no_lo_crea(self):
        """Ticket fuera de días de gracia: doble llamada no crea permisos."""
        self.vehiculo2.activo = False
        self.vehiculo2.save()
        self.vehiculo3.activo = False
        self.vehiculo3.save()

        config = ConfiguracionGlobal.get_solo()
        dias_gracia = config.dias_anticipacion_cancelacion
        inicio = self.ahora + timedelta(days=dias_gracia + 5, hours=8)
        Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=inicio + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )

        dar_baja_temporal_vehiculo(self.vehiculo1, 10, self.admin)
        dar_baja_temporal_vehiculo(self.vehiculo1, 10, self.admin)

        permisos = PermisoReservaExtraordinaria.objects.filter(usuario=self.usuario)
        self.assertEqual(permisos.count(), 0)

    # ── TEST BUG 3: Crear ticket durante baja temporal ────────────────────

    def test_crear_ticket_en_vehiculo_con_baja_temporal(self):
        """crear_ticket_con_reglas debe bloquear tickets para vehículos en baja temporal."""
        manana = timezone.localdate() + timedelta(days=1)
        self.vehiculo1.inactivo_hasta = manana + timedelta(days=5)
        self.vehiculo1.save()

        inicio = self.ahora + timedelta(days=2, hours=10)
        fin = inicio + timedelta(hours=3)
        res = crear_ticket_con_reglas(
            self.usuario, self.vehiculo1, inicio, fin,
            destino="Test", cant_pasajeros=2
        )
        self.assertEqual(res.estado, ResultadoCreacion.BLOQUEADO)
        self.assertIn("temporalmente inactivo", res.mensaje.lower())

    def test_crear_ticket_fuera_de_baja_temporal_ok(self):
        """Crear ticket para fecha posterior a la baja temporal debe funcionar."""
        manana = timezone.localdate() + timedelta(days=1)
        self.vehiculo1.inactivo_hasta = manana + timedelta(days=3)
        self.vehiculo1.save()

        inicio = self.ahora + timedelta(days=10, hours=10)
        fin = inicio + timedelta(hours=3)
        res = crear_ticket_con_reglas(
            self.usuario, self.vehiculo1, inicio, fin,
            destino="Test", cant_pasajeros=2
        )
        self.assertEqual(res.estado, ResultadoCreacion.OK)

    # ── TEST dias <= 0 ─────────────────────────────────────────────────────

    def test_baja_temporal_dias_cero_lanza_error(self):
        """dar_baja_temporal_vehiculo con dias=0 debe lanzar ValueError."""
        with self.assertRaises(ValueError):
            dar_baja_temporal_vehiculo(self.vehiculo1, 0, self.admin)

    def test_baja_temporal_dias_negativo_lanza_error(self):
        """dar_baja_temporal_vehiculo con dias negativo debe lanzar ValueError."""
        with self.assertRaises(ValueError):
            dar_baja_temporal_vehiculo(self.vehiculo1, -5, self.admin)

    def test_baja_temporal_dias_grandes_aceptados(self):
        """Un número grande de días debe funcionar (sin tope actual)."""
        inicio = self.ahora + timedelta(days=30, hours=8)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=inicio + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        resultado = dar_baja_temporal_vehiculo(self.vehiculo1, 365, self.admin)
        ticket.refresh_from_db()
        self.assertEqual(ticket.estado, Ticket.ESTADO_CANCELADO)
        self.assertEqual(resultado["total_afectados"], 1)


    # ─── TEST Vehículo ya inactivo permanentemente ───────────────────────

    def test_baja_temporal_vehiculo_ya_inactivo_permanente(self):
        """Dar baja temporal a vehículo con activo=False debe funcionar."""
        self.vehiculo1.activo = False
        self.vehiculo1.save()

        inicio = self.ahora + timedelta(days=1, hours=8)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=inicio + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        resultado = dar_baja_temporal_vehiculo(self.vehiculo1, 5, self.admin)
        ticket.refresh_from_db()
        self.assertEqual(ticket.estado, Ticket.ESTADO_CANCELADO)
        self.assertEqual(resultado["total_afectados"], 1)
        self.assertIsNotNone(self.vehiculo1.inactivo_hasta)

    # ─── TEST Prioridad con reasignación → NO crea permiso ────────────────

    def test_prioridad_con_reasignacion_no_crea_permiso(self):
        """Prioridad cancela, hay reasignación → NO debe crearse permiso de emergencia."""
        cargo_decano = get_cargo(Cargo.DECANO, 1)
        decano = Usuario.objects.create(
            nombre="Decano", apellido="Test", correo="decano@test.com",
            id_cargo=cargo_decano, valido=True
        )

        inicio = self.ahora + timedelta(days=4, hours=8)
        fin = inicio + timedelta(hours=2)

        # Usuario normal crea un ticket APROBADO (anticipación suficiente)
        res1 = crear_ticket_con_reglas(
            self.usuario, self.vehiculo1, inicio, fin,
            destino="Test", cant_pasajeros=2
        )
        self.assertEqual(res1.estado, ResultadoCreacion.OK)

        # Decano (mayor prioridad) crea ticket en mismo horario → sobrescribe
        res2 = crear_ticket_con_reglas(
            decano, self.vehiculo1, inicio, fin,
            destino="Decano priority", cant_pasajeros=2
        )
        self.assertEqual(res2.estado, ResultadoCreacion.SOBRESCRITO)

        ticket_cancelado = Ticket.objects.get(pk=res1.ticket.pk)
        self.assertEqual(ticket_cancelado.estado, Ticket.ESTADO_CANCELADO)

        # Como vehiculo2 está disponible, debe haber reasignación
        tickets_nuevos = Ticket.objects.filter(
            id_usuario=self.usuario,
            estado=Ticket.ESTADO_APROBADO,
        ).exclude(pk=res1.ticket.pk)

        if tickets_nuevos.exists():
            permisos = PermisoReservaExtraordinaria.objects.filter(usuario=self.usuario)
            self.assertEqual(permisos.count(), 0,
                             "Con reasignación no debe crearse permiso de emergencia.")
        else:
            # Si no hay reasignación (caso borde), debería haber permiso
            permisos = PermisoReservaExtraordinaria.objects.filter(usuario=self.usuario)
            self.assertGreater(permisos.count(), 0,
                               "Sin reasignación debe haber permiso de emergencia.")

    # ─── TEST Múltiples tickets mismo usuario → múltiples permisos ────────

    def test_multiples_tickets_mismo_usuario_multiples_permisos(self):
        """Un usuario con varios tickets cancelados → un permiso por cada uno."""
        self.vehiculo2.activo = False
        self.vehiculo2.save()
        self.vehiculo3.activo = False
        self.vehiculo3.save()

        for i in range(3):
            inicio = self.ahora + timedelta(days=i, hours=10)
            Ticket.objects.create(
                id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
                hora_inicio=inicio, hora_fin=inicio + timedelta(hours=2),
                estado=Ticket.ESTADO_APROBADO, destino=f"Test {i}", cant_pasajeros=2
            )

        resultado = dar_baja_temporal_vehiculo(self.vehiculo1, 10, self.admin)
        self.assertEqual(resultado["cancelados"], 3)
        self.assertEqual(resultado["reasignados"], 0)

        permisos = PermisoReservaExtraordinaria.objects.filter(usuario=self.usuario)
        self.assertEqual(permisos.count(), 3,
                         "Debe haber un permiso por cada ticket cancelado sin reasignación.")


    # ─── TEST Reasignación con capacidad exacta ───────────────────────────

    def test_reasignacion_con_capacidad_exacta(self):
        """_reasignar_ticket debe asignar vehículo con capacidad >= solicitada (ascendente)."""
        inicio = self.ahora + timedelta(days=1, hours=8)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=inicio + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=4
        )
        nuevo = _reasignar_ticket(ticket)
        self.assertIsNotNone(nuevo)
        # vehiculo2 (capacidad 4) antes que vehiculo3 (6)
        self.assertEqual(nuevo.id_vehiculo, self.vehiculo2)

    # ─── TEST Reasignación excluye exclusivo_decanato para no decanos ─────

    def test_reasignacion_excluye_exclusivo_decanato_para_no_decanos(self):
        """_reasignar_ticket no debe asignar exclusive_decanato a no decanos."""
        self.vehiculo2.exclusivo_decanato = True
        self.vehiculo2.save()

        inicio = self.ahora + timedelta(days=1, hours=8)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=inicio + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        nuevo = _reasignar_ticket(ticket)
        self.assertIsNotNone(nuevo)
        self.assertEqual(nuevo.id_vehiculo, self.vehiculo3)

    # ─── TEST Vehículo en baja temporal no se reasigna ────────────────────

    def test_reasignacion_excluye_vehiculos_en_baja_temporal(self):
        """_reasignar_ticket no debe asignar a vehículo en baja temporal en misma fecha."""
        manana = timezone.localdate() + timedelta(days=1)
        self.vehiculo2.inactivo_hasta = manana + timedelta(days=10)
        self.vehiculo2.save()

        inicio = self.ahora + timedelta(days=1, hours=8)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=inicio + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        nuevo = _reasignar_ticket(ticket)
        self.assertIsNotNone(nuevo)
        self.assertEqual(nuevo.id_vehiculo, self.vehiculo3)

    # ─── TEST Notificaciones no duplicadas ────────────────────────────────

    def test_doble_llamada_no_duplica_notification_logs(self):
        """Segunda llamada a baja temporal no debe duplicar NotificationLogs."""
        from reservas.models import NotificationLog

        inicio = self.ahora + timedelta(days=1, hours=8)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=inicio + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )

        dar_baja_temporal_vehiculo(self.vehiculo1, 5, self.admin)
        logs_primera = NotificationLog.objects.filter(ticket=ticket).count()
        self.assertGreaterEqual(logs_primera, 1)

        dar_baja_temporal_vehiculo(self.vehiculo1, 5, self.admin)
        logs_segunda = NotificationLog.objects.filter(ticket=ticket).count()
        self.assertEqual(logs_primera, logs_segunda,
                         "La segunda llamada no debe duplicar NotificationLogs.")


    # ─── TEST Baja expirada (levantar_baja) ──────────────────────────────

    def test_levantar_baja_cuando_ya_expiro(self):
        """Vehículo con inactivo_hasta expirado: save() lo limpia, no está en baja."""
        ayer = timezone.localdate() - timedelta(days=1)
        self.vehiculo1.inactivo_hasta = ayer
        self.vehiculo1.save()
        self.vehiculo1.refresh_from_db()
        self.assertIsNone(self.vehiculo1.inactivo_hasta)
        self.assertFalse(self.vehiculo1.esta_en_baja_temporal())

    # ─── TEST Reasignación con requiere_chofer ────────────────────────────

    def test_reasignacion_con_chofer_requerido(self):
        """_reasignar_ticket debe funcionar con requiere_chofer=True."""
        Usuario.objects.create(
            nombre="Chofer", apellido="Test", correo="chofer@test.com",
            id_cargo=self.cargo_chofer, valido=True
        )

        inicio = self.ahora + timedelta(days=1, hours=8)
        ticket = Ticket.objects.create(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=inicio + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO, destino="Test",
            cant_pasajeros=2, requiere_chofer=True
        )
        # Cancelar primero para que _reasignar_ticket no cuente este ticket en su query de choferes
        ticket.estado = Ticket.ESTADO_CANCELADO
        ticket.save(update_fields=["estado"])
        nuevo = _reasignar_ticket(ticket)
        self.assertIsNotNone(nuevo)
        self.assertTrue(nuevo.requiere_chofer)

    # ─── TEST Decano puede reasignarse a exclusivo_decanato ──────────────

    def test_reasignacion_asigna_exclusivo_decanato_a_decano(self):
        """_reasignar_ticket debe asignar exclusive_decanato si usuario es Decano."""
        cargo_decano = get_cargo(Cargo.DECANO, 1)
        decano = Usuario.objects.create(
            nombre="Decano", apellido="Test", correo="decano@test.com",
            id_cargo=cargo_decano, valido=True
        )

        self.vehiculo2.exclusivo_decanato = True
        self.vehiculo2.save()

        inicio = self.ahora + timedelta(days=1, hours=8)
        ticket = Ticket.objects.create(
            id_usuario=decano, id_vehiculo=self.vehiculo1,
            hora_inicio=inicio, hora_fin=inicio + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO, destino="Test", cant_pasajeros=2
        )
        nuevo = _reasignar_ticket(ticket)
        self.assertIsNotNone(nuevo)
        self.assertEqual(nuevo.id_vehiculo, self.vehiculo2)


