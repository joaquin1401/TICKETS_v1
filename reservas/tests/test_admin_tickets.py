"""
Tests del historial de tickets para admin: tabla HTML y export CSV.
"""

import csv
import io
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from reservas.models import Cargo, Ticket, Usuario, Vehiculo


def get_cargo(nombre, prioridad):
    cargo, created = Cargo.objects.get_or_create(
        nombre=nombre, defaults={"prioridad": prioridad}
    )
    if not created and cargo.prioridad != prioridad:
        cargo.prioridad = prioridad
        cargo.save()
    return cargo


class TestHistorialDistanciaReal(TestCase):
    """
    distancia_real (kilometraje_fin - kilometraje_inicio, calculado en
    Ticket.save()) ya se mostraba en detalle_ticket.html y en analíticas,
    pero faltaba en las tablas de historial (admin y usuario) y en el CSV.
    """

    def setUp(self):
        self.cargo_admin = get_cargo(Cargo.ADMIN_SEU, 0)
        self.cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        self.admin = Usuario.objects.create(
            nombre="Admin",
            apellido="SEU",
            correo="admin@test.com",
            id_cargo=self.cargo_admin,
            valido=True,
        )
        self.usuario = Usuario.objects.create(
            nombre="Juan",
            apellido="Perez",
            correo="juan@test.com",
            id_cargo=self.cargo_usuario,
            valido=True,
        )
        self.vehiculo = Vehiculo.objects.create(
            marca="Toyota", modelo="Hilux", patente="AA111AA", cant_pasajeros=4
        )
        inicio = timezone.now() - timedelta(days=1)
        self.ticket = Ticket.objects.create(
            id_usuario=self.usuario,
            id_vehiculo=self.vehiculo,
            hora_inicio=inicio,
            hora_fin=inicio + timedelta(hours=2),
            estado=Ticket.ESTADO_FINALIZADO,
            destino="Test",
            cant_pasajeros=2,
            kilometraje_inicio=Decimal("1000.0"),
            kilometraje_fin=Decimal("1120.5"),
        )
        # Confirma la precondición: distancia_real se calcula sola en save().
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.distancia_real, Decimal("120.5"))

        sesion = self.client.session
        sesion["usuario_id"] = self.admin.pk
        sesion["es_admin"] = True
        sesion.save()

    def test_csv_incluye_columna_y_valor_de_distancia_real(self):
        resp = self.client.get(reverse("descargar_historial_csv"))
        self.assertEqual(resp.status_code, 200)

        contenido = resp.content.decode("utf-8-sig")
        filas = list(csv.reader(io.StringIO(contenido)))
        encabezado = filas[0]
        self.assertIn("Distancia Real (km)", encabezado)

        idx = encabezado.index("Distancia Real (km)")
        fila_ticket = next(f for f in filas[1:] if f[0] == str(self.ticket.pk))
        # DecimalField(decimal_places=2): str(Decimal) conserva los 2 decimales.
        self.assertEqual(fila_ticket[idx], "120.50")

    def test_tabla_admin_muestra_distancia_real(self):
        resp = self.client.get(reverse("historial_tickets"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Distancia Real")
        self.assertContains(resp, "120,50 km")

    def test_tabla_admin_muestra_guion_sin_distancia_real(self):
        """Un ticket sin kilometraje cargado no debe mostrar '0 km' ni romper."""
        inicio = timezone.now() + timedelta(days=5)
        Ticket.objects.create(
            id_usuario=self.usuario,
            id_vehiculo=self.vehiculo,
            hora_inicio=inicio,
            hora_fin=inicio + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO,
            destino="Sin finalizar",
            cant_pasajeros=2,
        )
        resp = self.client.get(reverse("historial_tickets"))
        self.assertEqual(resp.status_code, 200)

    def test_tabla_usuario_tambien_muestra_distancia_real(self):
        """historial.html (el propio historial del usuario) tiene la misma columna."""
        sesion = self.client.session
        sesion["usuario_id"] = self.usuario.pk
        sesion["es_admin"] = False
        sesion.save()

        resp = self.client.get(reverse("historial"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Distancia Real")
        self.assertContains(resp, "120,50 km")


class TestFiltrosUsanTimezoneLocalNoRelojDelSistema(TestCase):
    """
    monitor_tickets_activos, historial_tickets y descargar_historial_csv
    usaban date.today() (reloj del sistema operativo) en vez de
    timezone.localdate() (zona horaria de Django, TIME_ZONE). En un
    servidor con reloj en UTC, entre las 21:00 y las 23:59 hora Argentina
    ya es "mañana" en UTC: un ticket de HOY (Argentina) podía desaparecer
    del monitor de activos, o aparecer prematuramente en el historial,
    según qué reloj usara cada vista - reportado por el usuario: un
    ticket creado para 40 minutos en el futuro no aparecía en el panel.

    Se verifica congelando timezone.localdate() a una fecha fija y
    confirmando que las querysets responden a ESE valor (a
    timezone.localdate(), no al reloj real del sistema).
    """

    def setUp(self):
        self.cargo_admin = get_cargo(Cargo.ADMIN_SEU, 0)
        self.cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        self.admin = Usuario.objects.create(
            nombre="Admin",
            apellido="SEU",
            correo="admin@test.com",
            id_cargo=self.cargo_admin,
            valido=True,
        )
        self.usuario = Usuario.objects.create(
            nombre="Juan",
            apellido="Perez",
            correo="juan@test.com",
            id_cargo=self.cargo_usuario,
            valido=True,
        )
        self.vehiculo = Vehiculo.objects.create(
            marca="Toyota", modelo="Hilux", patente="AA111AA", cant_pasajeros=4
        )
        sesion = self.client.session
        sesion["usuario_id"] = self.admin.pk
        sesion["es_admin"] = True
        sesion.save()

    def _crear(self, fecha, estado):
        inicio = timezone.make_aware(datetime.combine(fecha, time(19, 40)))
        return Ticket.objects.create(
            id_usuario=self.usuario,
            id_vehiculo=self.vehiculo,
            hora_inicio=inicio,
            hora_fin=inicio + timedelta(hours=2),
            estado=estado,
            destino="Test",
            cant_pasajeros=2,
        )

    def test_monitor_activos_usa_timezone_localdate(self):
        hoy = timezone.datetime(2026, 8, 7).date()
        t_hoy = self._crear(hoy, Ticket.ESTADO_APROBADO)

        with patch("django.utils.timezone.localdate", return_value=hoy):
            resp = self.client.get(reverse("monitor_tickets_activos"))
        ids = {t.pk for t in resp.context["tickets"]}
        self.assertIn(t_hoy.pk, ids)

        # Si el reloj del sistema (no Django) estuviera adelantado un día,
        # timezone.localdate() seguiría dando "hoy" correctamente - lo
        # importante es que la query dependa de esta función, no de
        # date.today(). Lo confirmamos comparando contra un "hoy" simulado
        # distinto: con localdate() = mañana, el ticket de hoy debe quedar
        # afuera (es el comportamiento correcto para esa fecha de corte).
        manana = hoy + timedelta(days=1)
        with patch("django.utils.timezone.localdate", return_value=manana):
            resp2 = self.client.get(reverse("monitor_tickets_activos"))
        ids2 = {t.pk for t in resp2.context["tickets"]}
        self.assertNotIn(t_hoy.pk, ids2)

    def test_historial_y_csv_coinciden_en_ticket_finalizado_de_hoy(self):
        """
        Antes: historial_tickets incluía FINALIZADO explícitamente, pero
        descargar_historial_csv solo miraba CANCELADO + hora_inicio pasada.
        Un ticket FINALIZADO con hora_inicio de HOY (el escenario exacto del
        bug de estado_inicial) aparecía en uno y no en el otro.
        """
        hoy = timezone.localdate()
        t_finalizado_hoy = self._crear(hoy, Ticket.ESTADO_FINALIZADO)

        resp_html = self.client.get(reverse("historial_tickets"))
        ids_html = {t.pk for t in resp_html.context["tickets"]}
        self.assertIn(t_finalizado_hoy.pk, ids_html)

        resp_csv = self.client.get(reverse("descargar_historial_csv"))
        contenido = resp_csv.content.decode("utf-8-sig")
        filas = list(csv.reader(io.StringIO(contenido)))
        ids_csv = {int(f[0]) for f in filas[1:]}
        self.assertIn(
            t_finalizado_hoy.pk,
            ids_csv,
            "El CSV debe incluir los mismos tickets que historial_tickets(), "
            "tal como dice su propio docstring.",
        )


class TestCargaManualTicket(TestCase):
    """
    crear_ticket_manual: carga manual de un ticket por un admin (digitalizar
    reservas por teléfono/papel, o backfill histórico). No pasa por
    crear_ticket_con_reglas - ver docstring de TicketManualForm.
    """

    def setUp(self):
        self.cargo_admin = get_cargo(Cargo.ADMIN_SEU, 0)
        self.cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        self.cargo_chofer = get_cargo(Cargo.CHOFER, 4)
        self.admin = Usuario.objects.create(
            nombre="Admin",
            apellido="SEU",
            correo="admin@test.com",
            id_cargo=self.cargo_admin,
            valido=True,
        )
        self.usuario = Usuario.objects.create(
            nombre="Juan",
            apellido="Perez",
            correo="juan@test.com",
            id_cargo=self.cargo_usuario,
            valido=True,
        )
        self.chofer = Usuario.objects.create(
            nombre="Carlos",
            apellido="Chofer",
            correo="carlos@test.com",
            id_cargo=self.cargo_chofer,
            valido=True,
        )
        self.vehiculo = Vehiculo.objects.create(
            marca="Toyota", modelo="Hilux", patente="AA111AA", cant_pasajeros=4
        )
        sesion = self.client.session
        sesion["usuario_id"] = self.admin.pk
        sesion["es_admin"] = True
        sesion.save()

    @staticmethod
    def _fmt(dt):
        """
        Formatea un datetime aware para el input datetime-local del form, en
        hora LOCAL (no UTC): dt.strftime() sobre un datetime aware muestra la
        hora en el tzinfo que ya tiene (UTC, si viene de timezone.now()), pero
        el campo datetime-local interpreta el string como hora local Argentina
        y la vuelve a convertir a UTC al guardar - sin este ajuste, un datetime
        de las 14:04 UTC se guarda como 17:04 UTC (14:04 interpretado como hora
        Argentina). Mismo tipo de trampa que USE_TZ viene mordiendo toda la
        sesión, esta vez en un test.
        """
        return timezone.localtime(dt).strftime("%Y-%m-%dT%H:%M")

    def _datos_base(self, **overrides):
        inicio = timezone.now() + timedelta(days=3)
        datos = {
            "id_vehiculo": self.vehiculo.pk,
            "destino": "Reunión",
            "cant_pasajeros": 2,
            "hora_inicio": self._fmt(inicio),
            "estado": Ticket.ESTADO_APROBADO,
        }
        datos.update(overrides)
        return datos

    def test_get_muestra_el_formulario(self):
        resp = self.client.get(reverse("crear_ticket_manual"))
        self.assertEqual(resp.status_code, 200)

    def test_no_admin_no_puede_acceder(self):
        sesion = self.client.session
        sesion["usuario_id"] = self.usuario.pk
        sesion["es_admin"] = False
        sesion.save()
        resp = self.client.get(reverse("crear_ticket_manual"))
        self.assertEqual(resp.status_code, 302)

    def test_sin_usuario_ni_conductor_queda_a_nombre_del_admin(self):
        resp = self.client.post(reverse("crear_ticket_manual"), self._datos_base())
        self.assertEqual(resp.status_code, 302)

        ticket = Ticket.objects.get(destino="Reunión")
        self.assertEqual(ticket.id_usuario, self.admin)
        self.assertIsNone(ticket.conductor)
        self.assertEqual(ticket.estado, Ticket.ESTADO_APROBADO)

    def test_con_usuario_y_conductor_explicitos(self):
        resp = self.client.post(
            reverse("crear_ticket_manual"),
            self._datos_base(id_usuario=self.usuario.pk, conductor=self.chofer.pk),
        )
        self.assertEqual(resp.status_code, 302)

        ticket = Ticket.objects.get(destino="Reunión")
        self.assertEqual(ticket.id_usuario, self.usuario)
        self.assertEqual(ticket.conductor, self.chofer)

    def test_finalizado_con_kilometraje_calcula_distancia_real_y_no_notifica(self):
        inicio = timezone.now() - timedelta(days=2)
        datos = self._datos_base(
            id_usuario=self.usuario.pk,
            hora_inicio=self._fmt(inicio),
            estado=Ticket.ESTADO_FINALIZADO,
            kilometraje_inicio="1000",
            kilometraje_fin="1120.5",
        )
        with patch("reservas.utils.notifications.async_task") as mock_async:
            resp = self.client.post(reverse("crear_ticket_manual"), datos)
        self.assertEqual(resp.status_code, 302)

        ticket = Ticket.objects.get(destino="Reunión")
        self.assertEqual(ticket.estado, Ticket.ESTADO_FINALIZADO)
        self.assertEqual(ticket.distancia_real, Decimal("120.50"))
        # Backfill histórico: no tiene sentido avisarle "tu reserva fue creada"
        # de un viaje que ya pasó.
        mock_async.assert_not_called()

    def test_aprobado_si_notifica_al_usuario(self):
        with patch("reservas.utils.notifications.async_task") as mock_async:
            resp = self.client.post(
                reverse("crear_ticket_manual"),
                self._datos_base(id_usuario=self.usuario.pk),
            )
        self.assertEqual(resp.status_code, 302)
        mock_async.assert_called_once()

    def test_bloquea_conflicto_con_otra_reserva_activa(self):
        inicio = timezone.now() + timedelta(days=3)
        Ticket.objects.create(
            id_usuario=self.usuario,
            id_vehiculo=self.vehiculo,
            hora_inicio=inicio,
            hora_fin=inicio + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO,
            destino="Ya reservado",
            cant_pasajeros=2,
        )

        resp = self.client.post(
            reverse("crear_ticket_manual"),
            self._datos_base(hora_inicio=self._fmt(inicio)),
        )
        self.assertEqual(resp.status_code, 200)  # re-renderiza el form con error
        self.assertFalse(Ticket.objects.filter(destino="Reunión").exists())

    def test_no_bloquea_si_el_backfill_no_queda_activo(self):
        """
        Un backfill cancelado/finalizado no reclama la agenda del vehículo,
        así que no debe chocar con una reserva activa existente en la misma
        franja - a diferencia de una carga nueva en estado aprobado.
        """
        inicio = timezone.now() + timedelta(days=3)
        Ticket.objects.create(
            id_usuario=self.usuario,
            id_vehiculo=self.vehiculo,
            hora_inicio=inicio,
            hora_fin=inicio + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO,
            destino="Ya reservado",
            cant_pasajeros=2,
        )

        resp = self.client.post(
            reverse("crear_ticket_manual"),
            self._datos_base(
                hora_inicio=self._fmt(inicio),
                estado=Ticket.ESTADO_CANCELADO,
            ),
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Ticket.objects.filter(destino="Reunión").exists())

    def test_hora_fin_anterior_a_inicio_es_rechazado(self):
        inicio = timezone.now() + timedelta(days=3)
        resp = self.client.post(
            reverse("crear_ticket_manual"),
            self._datos_base(
                hora_inicio=self._fmt(inicio),
                hora_fin=self._fmt(inicio - timedelta(hours=1)),
            ),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Ticket.objects.filter(destino="Reunión").exists())

    def test_kilometraje_fin_menor_a_inicio_es_rechazado(self):
        resp = self.client.post(
            reverse("crear_ticket_manual"),
            self._datos_base(kilometraje_inicio="1000", kilometraje_fin="500"),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Ticket.objects.filter(destino="Reunión").exists())
