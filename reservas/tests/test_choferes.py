"""
Tests del dashboard de chofer: ventana de "Próximos Viajes".
"""

from datetime import datetime, time
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


class TestProximosViajesVentana(TestCase):
    """
    La ventana de "Próximos Viajes" muestra tickets aprobados sin conductor
    desde mañana hasta 2 días hábiles desde hoy (domingo no cuenta, sábado
    sí - ver agregar_dias_habiles en utils/services.py).

    "Hoy" se congela en viernes 2026-08-07 con mock.patch sobre
    timezone.localdate, para que el test no dependa del día real en que
    se corra: con la ventana de 2 días hábiles, el corte cae el lunes
    2026-08-10 (sábado 8 cuenta, domingo 9 no, lunes 10 es el segundo).
    """

    HOY = timezone.datetime(2026, 8, 7).date()  # viernes

    def setUp(self):
        self.cargo_chofer = get_cargo(Cargo.CHOFER, 4)
        self.cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        self.chofer = Usuario.objects.create(
            nombre="Carlos",
            apellido="Chofer",
            correo="chofer@test.com",
            id_cargo=self.cargo_chofer,
            valido=True,
        )
        self.solicitante = Usuario.objects.create(
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
        sesion["usuario_id"] = self.chofer.pk
        sesion["es_admin"] = False
        sesion.save()

    def _crear_ticket_sin_conductor(self, fecha):
        inicio = timezone.make_aware(datetime.combine(fecha, time(10, 0)))
        return Ticket.objects.create(
            id_usuario=self.solicitante,
            id_vehiculo=self.vehiculo,
            hora_inicio=inicio,
            hora_fin=inicio + timezone.timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO,
            destino="Test",
            cant_pasajeros=2,
            conductor=None,
        )

    def test_ventana_incluye_manana_y_el_limite_de_2_dias_habiles(self):
        # sábado 8 (mañana, 1er día hábil) y lunes 10 (2do día hábil, el corte)
        t_manana = self._crear_ticket_sin_conductor(
            timezone.datetime(2026, 8, 8).date()
        )
        t_limite = self._crear_ticket_sin_conductor(
            timezone.datetime(2026, 8, 10).date()
        )

        with patch("django.utils.timezone.localdate", return_value=self.HOY):
            resp = self.client.get(reverse("chofer_dashboard"))

        self.assertEqual(resp.status_code, 200)
        ids_mostrados = {t.pk for t in resp.context["tickets_futuros"]}
        self.assertIn(t_manana.pk, ids_mostrados)
        self.assertIn(t_limite.pk, ids_mostrados)

    def test_ventana_excluye_un_dia_habil_despues_del_limite(self):
        # martes 11 - un día hábil más allá del corte (lunes 10)
        t_afuera = self._crear_ticket_sin_conductor(
            timezone.datetime(2026, 8, 11).date()
        )

        with patch("django.utils.timezone.localdate", return_value=self.HOY):
            resp = self.client.get(reverse("chofer_dashboard"))

        ids_mostrados = {t.pk for t in resp.context["tickets_futuros"]}
        self.assertNotIn(t_afuera.pk, ids_mostrados)

    def test_ventana_excluye_hoy_mismo(self):
        # hoy mismo va en la sección "Viajes de Hoy", no en "Próximos Viajes"
        t_hoy = self._crear_ticket_sin_conductor(self.HOY)

        with patch("django.utils.timezone.localdate", return_value=self.HOY):
            resp = self.client.get(reverse("chofer_dashboard"))

        ids_futuros = {t.pk for t in resp.context["tickets_futuros"]}
        ids_hoy = {t.pk for t in resp.context["tickets_hoy"]}
        self.assertNotIn(t_hoy.pk, ids_futuros)
        self.assertIn(t_hoy.pk, ids_hoy)

    def test_ventana_ya_no_es_de_7_dias_corridos(self):
        """
        Regresión: antes la ventana era +7 días corridos, así que un viaje el
        12/8 (5 días desde el viernes 7/8) hubiera aparecido. Con 2 días
        hábiles el corte es el 10/8, así que el 12/8 debe quedar afuera.
        """
        t_viejo_alcance = self._crear_ticket_sin_conductor(
            timezone.datetime(2026, 8, 12).date()
        )

        with patch("django.utils.timezone.localdate", return_value=self.HOY):
            resp = self.client.get(reverse("chofer_dashboard"))

        ids_mostrados = {t.pk for t in resp.context["tickets_futuros"]}
        self.assertNotIn(t_viejo_alcance.pk, ids_mostrados)
