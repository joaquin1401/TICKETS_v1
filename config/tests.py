from unittest.mock import patch

from django.db.utils import OperationalError
from django.test import TestCase
from django.urls import reverse


class TestHealthz(TestCase):
    def test_healthz_ok_con_bd_disponible(self):
        resp = self.client.get(reverse("healthz"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_healthz_no_requiere_sesion(self):
        """Es un probe de infraestructura: debe responder sin login."""
        self.assertNotIn("usuario_id", self.client.session)
        resp = self.client.get(reverse("healthz"))
        self.assertEqual(resp.status_code, 200)

    def test_healthz_503_si_falla_la_bd(self):
        """
        Parcheamos connection.cursor() tal como lo importa config/views.py, no
        el backend de Django en general: si patcheáramos algo más amplio
        (django.db.backends.utils.CursorWrapper.execute), también
        interceptaríamos las queries que hace el middleware de sesión en el
        mismo request, y estaríamos probando otra cosa.
        """
        with patch(
            "config.views.connection.cursor", side_effect=OperationalError("boom")
        ):
            resp = self.client.get(reverse("healthz"))
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["status"], "error")
