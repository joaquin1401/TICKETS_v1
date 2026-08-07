"""
Tests de constraints e invariantes a nivel de modelo/BD (no de reglas de
negocio de más alto nivel - esas viven en test_booking_rules.py).
"""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
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


class TestTicketHoraFinConstraint(TestCase):
    """
    ticket_hora_fin_posterior_a_hora_inicio: hora_fin, cuando no es NULL,
    tiene que ser estrictamente posterior a hora_inicio. Antes esto solo se
    validaba en TicketForm.clean() - un create() directo por ORM (admin,
    poblar_bd, un fixture) no tenía nada que lo impidiera.
    """

    def setUp(self):
        self.cargo = get_cargo(Cargo.USUARIO, 3)
        self.usuario = Usuario.objects.create(
            nombre="Juan",
            apellido="Perez",
            correo="juan@test.com",
            id_cargo=self.cargo,
            valido=True,
        )
        self.vehiculo = Vehiculo.objects.create(
            marca="Toyota", modelo="Corolla", patente="AA111AA", cant_pasajeros=4
        )
        self.ahora = timezone.now()

    def _crear_ticket(self, hora_inicio, hora_fin):
        return Ticket.objects.create(
            id_usuario=self.usuario,
            id_vehiculo=self.vehiculo,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
            destino="Test",
            cant_pasajeros=2,
        )

    def test_hora_fin_igual_a_hora_inicio_viola_la_constraint(self):
        inicio = self.ahora + timedelta(days=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._crear_ticket(inicio, inicio)

    def test_hora_fin_anterior_a_hora_inicio_viola_la_constraint(self):
        inicio = self.ahora + timedelta(days=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._crear_ticket(inicio, inicio - timedelta(hours=1))

    def test_hora_fin_posterior_es_valida(self):
        inicio = self.ahora + timedelta(days=1)
        ticket = self._crear_ticket(inicio, inicio + timedelta(hours=2))
        self.assertIsNotNone(ticket.pk)

    def test_hora_fin_null_es_valida(self):
        inicio = self.ahora + timedelta(days=1)
        ticket = self._crear_ticket(inicio, None)
        self.assertIsNotNone(ticket.pk)
