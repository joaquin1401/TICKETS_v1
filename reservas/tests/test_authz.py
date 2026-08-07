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
        self.vehiculo = Vehiculo.objects.create(
            marca="Toyota", modelo="Hilux", patente="AA111AA", cant_pasajeros=4
        )
        self.ticket_ajeno = Ticket.objects.create(
            id_usuario=self.usuario,
            id_vehiculo=self.vehiculo,
            destino="Resistencia",
            cant_pasajeros=2,
            hora_inicio=timezone.now() + timedelta(days=5),
            hora_fin=timezone.now() + timedelta(days=5, hours=2),
            estado=Ticket.ESTADO_APROBADO,
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

    # ── admin_requerido revalida contra la BD en cada request ─────────────────────

    def test_admin_requerido_bloquea_tras_degradar_cargo_con_sesion_activa(self):
        """
        admin_requerido ya NO confía en session["es_admin"] (una foto fijada
        una sola vez en login_view): recalcula usuario.id_cargo.prioridad == 0
        contra la BD en cada request. Si a un admin le bajan el cargo mientras
        su sesión sigue activa, pierde el acceso admin de inmediato, sin
        esperar a que vuelva a loguearse.

        session["es_admin"] queda deliberadamente en True acá (como habría
        quedado desde el login original) para probar que ya no se usa esa
        key para autorizar.
        """
        self._loguear_como(self.admin, es_admin=True)

        # Degradar al admin DESPUÉS de que su sesión ya quedó establecida.
        self.admin.id_cargo = self.cargo_usuario
        self.admin.save(update_fields=["id_cargo"])

        resp = self.client.get(reverse("listado_vehiculos"))
        self.assertEqual(
            resp.status_code,
            302,
            "usuario.id_cargo.prioridad ya no es 0: admin_requerido debe "
            "bloquear aunque session['es_admin'] siga en True.",
        )
        self.assertEqual(resp.url, reverse("inicio"))

    def test_admin_requerido_permite_tras_ascender_cargo_con_sesion_activa(self):
        """Contraparte: ascender a alguien a admin debe habilitarlo al instante."""
        self._loguear_como(self.usuario, es_admin=False)

        self.usuario.id_cargo = self.cargo_admin
        self.usuario.save(update_fields=["id_cargo"])

        resp = self.client.get(reverse("listado_vehiculos"))
        self.assertEqual(
            resp.status_code,
            200,
            "usuario.id_cargo.prioridad ya es 0: admin_requerido debe dejarlo "
            "pasar aunque session['es_admin'] siga en False.",
        )

    def test_detalle_ticket_no_expone_ticket_ajeno_tras_degradar_admin(self):
        """
        detalle_ticket() dejaba ver el ticket de CUALQUIER usuario si
        session["es_admin"] era True, sin revalidar contra la BD. Un admin
        degradado con la sesión todavía abierta podía seguir abriendo por
        URL el detalle (destino, pasajero, observaciones) de tickets que no
        eran suyos. Ahora debe recalcular el cargo y tratarlo como usuario
        normal: 404 si el ticket no le pertenece.
        """
        self._loguear_como(self.admin, es_admin=True)

        self.admin.id_cargo = self.cargo_usuario
        self.admin.save(update_fields=["id_cargo"])

        resp = self.client.get(reverse("detalle_ticket", args=[self.ticket_ajeno.pk]))
        self.assertEqual(
            resp.status_code,
            404,
            "El ticket es de otro usuario: no debe ser visible aunque "
            "session['es_admin'] siga en True.",
        )
