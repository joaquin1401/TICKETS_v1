"""
Tests de autenticación.

A diferencia de test_views.py (que usa RequestFactory y llama a las vistas
directamente), estos tests usan self.client, con lo cual pasan por el stack
real de middleware: sesiones, CSRF y mensajes.
"""

from django.test import TestCase
from django.urls import reverse

from reservas.models import Cargo, Usuario


PASSWORD_VALIDA = "Trayecto-Vehiculo-91"


class TestLogin(TestCase):
    def setUp(self):
        self.cargo = Cargo.objects.create(nombre=Cargo.USUARIO, prioridad=3)
        self.usuario = Usuario(
            nombre="Juan",
            apellido="Perez",
            correo="juan@test.com",
            id_cargo=self.cargo,
            valido=True,
            correo_verificado=True,
        )
        self.usuario.set_password(PASSWORD_VALIDA)
        self.usuario.save()

    def _iniciar_sesion_anonima(self):
        """Fuerza la creación de una sesión previa al login y devuelve su key."""
        sesion = self.client.session
        sesion["dato_previo"] = "1"
        sesion.save()
        return sesion.session_key

    def test_login_exitoso_establece_sesion(self):
        resp = self.client.post(
            reverse("login"),
            {"correo": "juan@test.com", "contrasena": PASSWORD_VALIDA},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.session["usuario_id"], self.usuario.pk)
        self.assertFalse(self.client.session["es_admin"])

    def test_login_rota_la_session_key(self):
        """
        Regresión: sin cycle_key(), un session id fijado por un atacante antes
        del login sigue siendo válido después (session fixation).
        """
        key_previa = self._iniciar_sesion_anonima()
        self.assertIsNotNone(key_previa)

        self.client.post(
            reverse("login"),
            {"correo": "juan@test.com", "contrasena": PASSWORD_VALIDA},
        )

        self.assertNotEqual(key_previa, self.client.session.session_key)
        self.assertEqual(self.client.session["usuario_id"], self.usuario.pk)

    def test_password_incorrecta_no_establece_sesion(self):
        resp = self.client.post(
            reverse("login"),
            {"correo": "juan@test.com", "contrasena": "no-es-la-password"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("usuario_id", self.client.session)

    def test_logout_limpia_la_sesion(self):
        self.client.post(
            reverse("login"),
            {"correo": "juan@test.com", "contrasena": PASSWORD_VALIDA},
        )
        self.assertIn("usuario_id", self.client.session)

        self.client.get(reverse("logout"))
        self.assertNotIn("usuario_id", self.client.session)
