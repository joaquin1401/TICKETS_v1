"""
Smoke tests de las vistas de analíticas (reservas/views/analiticas.py).

No existía ningún test para este módulo: un NameError en
reporte_analiticas_pdf() (variable `hoy` usada después de haber sido
sacada de la función al extraer calcular_rango_fechas()) pasó los 144
tests de la suite sin que nada lo detectara - solo lo agarró ruff
(F821, análisis estático). Estos tests cubren al menos que las tres
vistas respondan 200 para cada valor de `rango`, sin reventar.
"""

from datetime import timedelta

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


class TestVistasAnaliticas(TestCase):
    def setUp(self):
        self.cargo_admin = get_cargo(Cargo.ADMIN_SEU, 0)
        self.admin = Usuario.objects.create(
            nombre="Admin",
            apellido="SEU",
            correo="admin_analiticas@test.com",
            id_cargo=self.cargo_admin,
            valido=True,
            correo_verificado=True,
        )
        self.vehiculo = Vehiculo.objects.create(
            marca="Toyota", modelo="Hilux", patente="AA111AA", cant_pasajeros=4
        )
        inicio = timezone.now() - timedelta(days=5)
        Ticket.objects.create(
            id_usuario=self.admin,
            id_vehiculo=self.vehiculo,
            destino="Resistencia",
            cant_pasajeros=2,
            hora_inicio=inicio,
            hora_fin=inicio + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO,
        )

        sesion = self.client.session
        sesion["usuario_id"] = self.admin.pk
        sesion["es_admin"] = True
        sesion.save()

    def test_reporte_analiticas_responde_200_para_cada_rango(self):
        for rango in ["30d", "90d", "anio", "todo", ""]:
            resp = self.client.get(reverse("reporte_analiticas"), {"rango": rango})
            self.assertEqual(resp.status_code, 200, f"rango={rango!r}")

    def test_analiticas_vehiculo_responde_200_para_cada_rango(self):
        for rango in ["30d", "90d", "anio", "todo", ""]:
            resp = self.client.get(
                reverse("analiticas_vehiculo", args=[self.vehiculo.pk]),
                {"rango": rango},
            )
            self.assertEqual(resp.status_code, 200, f"rango={rango!r}")

    def test_reporte_analiticas_pdf_responde_200_para_cada_rango(self):
        """
        El caso que rompía: reporte_analiticas_pdf() usa `hoy` en
        fecha_generacion y en el nombre del archivo, después del bloque que
        ahora vive en calcular_rango_fechas().
        """
        for rango in ["30d", "90d", "anio", "todo", ""]:
            resp = self.client.get(reverse("reporte_analiticas_pdf"), {"rango": rango})
            self.assertEqual(resp.status_code, 200, f"rango={rango!r}")
            self.assertEqual(resp["Content-Type"], "application/pdf")
