"""
Tests de autorización: @login_requerido, @admin_requerido, @chofer_requerido
y @sin_chofer_requerido (definidos en reservas/views/_base.py).

Usan self.client (stack real de middleware) y fijan la sesión directamente
vía self.client.session, el mismo mecanismo que usa la propia app
(session["usuario_id"] / session["es_admin"]) - no hace falta pasar por
login_view para cada caso.

Antes de esto no había ningún test que confirmara que un usuario no-admin
es efectivamente bloqueado de una vista de admin: @admin_requerido confía
en session["es_admin"], y nada verificaba que esa confianza se sostuviera.
"""

from django.test import TestCase
from django.urls import reverse

from reservas.models import Cargo, Usuario


def get_cargo(nombre, prioridad):
    cargo, created = Cargo.objects.get_or_create(
        nombre=nombre, defaults={"prioridad": prioridad}
    )
    if not created and cargo.prioridad != prioridad:
        cargo.prioridad = prioridad
        cargo.save()
    return cargo


class TestAutorizacion(TestCase):
    def setUp(self):
        self.cargo_admin = get_cargo(Cargo.ADMIN_SEU, 0)
        self.cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        self.cargo_chofer = get_cargo(Cargo.CHOFER, 4)

        self.admin = Usuario.objects.create(
            nombre="Admin",
            apellido="SEU",
            correo="admin_authz@test.com",
            id_cargo=self.cargo_admin,
            valido=True,
            correo_verificado=True,
        )
        self.usuario = Usuario.objects.create(
            nombre="Juan",
            apellido="Perez",
            correo="usuario_authz@test.com",
            id_cargo=self.cargo_usuario,
            valido=True,
            correo_verificado=True,
        )
        self.chofer = Usuario.objects.create(
            nombre="Carlos",
            apellido="Chofer",
            correo="chofer_authz@test.com",
            id_cargo=self.cargo_chofer,
            valido=True,
            correo_verificado=True,
        )

    def _loguear_como(self, usuario, es_admin=None):
        """
        Fija la sesión directamente, igual que hace login_view tras validar
        credenciales - sin repetir el flujo de login en cada test.
        """
        if es_admin is None:
            es_admin = usuario.id_cargo.prioridad == 0
        sesion = self.client.session
        sesion["usuario_id"] = usuario.pk
        sesion["es_admin"] = es_admin
        sesion.save()

    # ── @login_requerido ─────────────────────────────────────────────────────────

    def test_login_requerido_bloquea_anonimo(self):
        """Sin sesión, una vista @login_requerido redirige a login (no 200)."""
        resp = self.client.get(reverse("inicio"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("login"))

    def test_login_requerido_bloquea_usuario_eliminado(self):
        """Si el usuario de la sesión ya no existe en la BD, se limpia la sesión y redirige."""
        self._loguear_como(self.usuario)
        self.usuario.delete()

        resp = self.client.get(reverse("inicio"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("login"))
        self.assertNotIn("usuario_id", self.client.session)

    # ── @admin_requerido ─────────────────────────────────────────────────────────

    def test_admin_requerido_bloquea_usuario_normal(self):
        """Un usuario logueado pero no-admin no puede entrar a una vista de admin."""
        self._loguear_como(self.usuario, es_admin=False)

        resp = self.client.get(reverse("listado_vehiculos"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("inicio"))

    def test_admin_requerido_bloquea_chofer(self):
        """Un chofer tampoco es admin: mismo bloqueo que un usuario normal."""
        self._loguear_como(self.chofer, es_admin=False)

        resp = self.client.get(reverse("listado_vehiculos"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("inicio"))

    def test_admin_requerido_permite_admin(self):
        """Un admin real (session["es_admin"]=True) sí entra."""
        self._loguear_como(self.admin, es_admin=True)

        resp = self.client.get(reverse("listado_vehiculos"))
        self.assertEqual(resp.status_code, 200)

    def test_admin_requerido_sin_sesion_redirige_a_login_no_a_inicio(self):
        """
        Sin sesión activa, @login_requerido (que corre primero en la pila) debe
        interceptar antes que @admin_requerido - el mensaje de "sin permisos"
        de admin_requerido no debería verse en este caso.
        """
        resp = self.client.get(reverse("listado_vehiculos"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("login"))

    # ── @chofer_requerido ────────────────────────────────────────────────────────

    def test_chofer_requerido_bloquea_usuario_normal(self):
        self._loguear_como(self.usuario, es_admin=False)

        resp = self.client.get(reverse("chofer_dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("inicio"))

    def test_chofer_requerido_permite_chofer(self):
        self._loguear_como(self.chofer, es_admin=False)

        resp = self.client.get(reverse("chofer_dashboard"))
        self.assertEqual(resp.status_code, 200)

    def test_chofer_requerido_permite_admin(self):
        """El decorador deja pasar también a un admin (escape hatch explícito)."""
        self._loguear_como(self.admin, es_admin=True)

        resp = self.client.get(reverse("chofer_dashboard"))
        self.assertEqual(resp.status_code, 200)

    # ── @sin_chofer_requerido ────────────────────────────────────────────────────

    def test_sin_chofer_requerido_redirige_chofer_a_su_dashboard(self):
        """Un chofer no puede usar la vista de reserva de usuarios normales."""
        self._loguear_como(self.chofer, es_admin=False)

        resp = self.client.get(reverse("inicio"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("chofer_dashboard"))

    def test_sin_chofer_requerido_permite_usuario_normal(self):
        self._loguear_como(self.usuario, es_admin=False)

        resp = self.client.get(reverse("inicio"))
        self.assertEqual(resp.status_code, 200)

    # ── Límite conocido: session["es_admin"] no se revalida en cada request ───────

    def test_LIMITACION_conocida_sesion_admin_no_se_revalida_tras_degradar_cargo(self):
        """
        Documenta un gap real, no una garantía deseable: session["es_admin"] se
        fija UNA VEZ en login_view y nunca se vuelve a comparar contra el cargo
        actual del usuario en la BD. Si a un admin le bajan el cargo (o pierde
        prioridad 0) mientras su sesión sigue activa (hasta 8h, SESSION_COOKIE_AGE),
        sigue pasando @admin_requerido hasta que vuelva a loguearse.

        Este test verifica el comportamiento ACTUAL para dejarlo detectable si
        algún día se decide revalidar en cada request (en cuyo momento este test
        debería empezar a fallar, y hay que actualizarlo a la espera del arreglo).
        """
        self._loguear_como(self.admin, es_admin=True)

        # Degradar al admin DESPUÉS de que su sesión ya quedó establecida.
        self.admin.id_cargo = self.cargo_usuario
        self.admin.save(update_fields=["id_cargo"])

        resp = self.client.get(reverse("listado_vehiculos"))
        self.assertEqual(
            resp.status_code,
            200,
            "Comportamiento actual: la sesión vieja sigue pasando @admin_requerido "
            "aunque el usuario ya no sea admin en la BD.",
        )
