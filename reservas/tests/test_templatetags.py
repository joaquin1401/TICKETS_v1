"""
Tests del filtro badge_estado (reservas/templatetags/estado_tags.py).

Antes, 5 templates repetían a mano un if/elif que solo distinguía
'aprobado'/'cancelado' y mandaba todo lo demás (incluidos en_curso y
finalizado) a "warning" - el mismo color que pendiente.
"""

from django.test import SimpleTestCase

from reservas.models import Ticket
from reservas.templatetags.estado_tags import badge_estado


class TestBadgeEstado(SimpleTestCase):
    def test_cada_estado_tiene_su_propio_color(self):
        colores = {
            Ticket.ESTADO_PENDIENTE: "warning",
            Ticket.ESTADO_APROBADO: "success",
            Ticket.ESTADO_EN_CURSO: "info",
            Ticket.ESTADO_FINALIZADO: "neutral",
            Ticket.ESTADO_CANCELADO: "danger",
        }
        for estado, color in colores.items():
            self.assertEqual(badge_estado(estado), color)

        # en_curso y finalizado ya no comparten color con pendiente.
        self.assertNotEqual(
            badge_estado(Ticket.ESTADO_EN_CURSO), badge_estado(Ticket.ESTADO_PENDIENTE)
        )
        self.assertNotEqual(
            badge_estado(Ticket.ESTADO_FINALIZADO),
            badge_estado(Ticket.ESTADO_PENDIENTE),
        )

    def test_estado_desconocido_cae_en_neutral_no_en_otro_color(self):
        """
        Si el modelo agrega un estado nuevo y se olvidan de mapearlo acá,
        debe cambiar a un color explícitamente "no sé qué es esto", no
        heredar el color de otro estado por accidente de orden en un if/elif.
        """
        self.assertEqual(badge_estado("estado_inexistente"), "neutral")
