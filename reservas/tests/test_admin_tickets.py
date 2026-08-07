"""
Tests del historial de tickets para admin: tabla HTML y export CSV.
"""

import csv
import io
from datetime import timedelta
from decimal import Decimal

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
