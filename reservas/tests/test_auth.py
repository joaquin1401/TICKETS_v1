"""
Tests de autenticación.

A diferencia de test_views.py (que usa RequestFactory y llama a las vistas
directamente), estos tests usan self.client, con lo cual pasan por el stack
real de middleware: sesiones, CSRF y mensajes.
"""

from unittest.mock import patch

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


class TestRateLimitingLogin(TestCase):
    """
    Rate limiting de login (reservas/utils/rate_limit.py): tras demasiados
    intentos fallidos recientes, se bloquea el intento SIN validar
    credenciales, aunque la contraseña sea la correcta.
    """

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

    def _intentar_login(self, correo, contrasena):
        return self.client.post(
            reverse("login"), {"correo": correo, "contrasena": contrasena}
        )

    def test_bloqueado_por_correo_tras_agotar_intentos(self):
        from reservas.utils.rate_limit import MAX_INTENTOS_POR_CORREO

        for _ in range(MAX_INTENTOS_POR_CORREO):
            resp = self._intentar_login("juan@test.com", "password-incorrecta")
            self.assertEqual(resp.status_code, 200)

        # Ahora, con la contraseña CORRECTA: igual debe bloquear, porque ya
        # se agotaron los intentos permitidos para este correo.
        resp = self._intentar_login("juan@test.com", PASSWORD_VALIDA)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("usuario_id", self.client.session)
        mensajes = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("Demasiados intentos" in m for m in mensajes))

    def test_bloqueado_por_ip_tras_agotar_intentos_con_correos_distintos(self):
        from reservas.utils.rate_limit import MAX_INTENTOS_POR_IP

        # Todos los requests de self.client comparten la misma IP (127.0.0.1
        # por default): probar con un correo DISTINTO en cada intento evita
        # tropezar con el límite por-correo, y aísla el límite por-IP.
        for i in range(MAX_INTENTOS_POR_IP):
            resp = self._intentar_login(f"inexistente{i}@test.com", "cualquiera")
            self.assertEqual(resp.status_code, 200)

        resp = self._intentar_login("juan@test.com", PASSWORD_VALIDA)
        self.assertNotIn("usuario_id", self.client.session)
        mensajes = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("Demasiados intentos" in m for m in mensajes))

    def test_no_bloquea_por_debajo_del_limite(self):
        from reservas.utils.rate_limit import MAX_INTENTOS_POR_CORREO

        for _ in range(MAX_INTENTOS_POR_CORREO - 1):
            self._intentar_login("juan@test.com", "password-incorrecta")

        resp = self._intentar_login("juan@test.com", PASSWORD_VALIDA)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.session["usuario_id"], self.usuario.pk)


class TestRateLimitingRecuperacionPassword(TestCase):
    """
    Rate limiting del código de recuperación (RecuperacionPassword.
    MAX_INTENTOS_CODIGO): protege contra fuerza bruta sobre el código de 6
    dígitos, que de otro modo tiene 10**6 combinaciones dentro de una ventana
    de 30 minutos.
    """

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

        from reservas.utils.password_recovery import crear_recuperacion

        self.recuperacion = crear_recuperacion(self.usuario)

        # Simula la sesión que solicitar_recuperacion() deja tras pedir el
        # código - no hace falta pasar por esa vista para este test.
        sesion = self.client.session
        sesion["recuperacion_uid"] = self.usuario.pk
        sesion.save()

    def _intentar_codigo(self, codigo):
        return self.client.post(reverse("verificar_recuperacion"), {"codigo": codigo})

    def test_codigo_correcto_deja_de_funcionar_tras_agotar_intentos(self):
        from reservas.models import RecuperacionPassword

        # El intento que hace que intentos_fallidos llegue a MAX_INTENTOS_CODIGO
        # es el que reporta "agotaste los intentos" explícitamente. Uno más
        # allá de ese, esta_vigente() ya corta antes y devuelve "expiró" en su
        # lugar (mismo resultado práctico, mensaje distinto) - por eso se
        # verifica el mensaje justo en el intento que cruza el umbral, no en
        # uno posterior.
        resp = None
        for _ in range(RecuperacionPassword.MAX_INTENTOS_CODIGO):
            resp = self._intentar_codigo("000000")  # nunca es el código real

        mensajes = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("Agotaste los intentos" in m for m in mensajes))

        self.recuperacion.refresh_from_db()
        self.assertFalse(self.recuperacion.esta_vigente())

        # El código real, el que se mandó por correo, ya no sirve: se agotaron
        # los intentos aunque falten minutos para que expire por tiempo.
        self._intentar_codigo(self.recuperacion.codigo)
        self.assertNotIn("can_reset_password", self.client.session)

    def test_codigo_correcto_funciona_por_debajo_del_limite(self):
        from reservas.models import RecuperacionPassword

        for _ in range(RecuperacionPassword.MAX_INTENTOS_CODIGO - 1):
            self._intentar_codigo("000000")

        resp = self._intentar_codigo(self.recuperacion.codigo)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self.client.session.get("can_reset_password"))


class TestRateLimitingVerificacionCorreo(TestCase):
    """
    Rate limiting del código de verificación de correo (VerificacionCorreo.
    MAX_INTENTOS_CODIGO). Mismo mecanismo y mismo motivo que
    TestRateLimitingRecuperacionPassword: el código de 6 dígitos tiene 10**6
    combinaciones y, antes de agregar intentos_fallidos a este modelo, no
    había ningún límite acá (a diferencia de RecuperacionPassword, que sí lo
    tenía desde antes) - se podían probar las 10**6 dentro de la ventana de
    30 minutos.
    """

    def setUp(self):
        self.cargo = Cargo.objects.create(nombre=Cargo.USUARIO, prioridad=3)
        self.usuario = Usuario(
            nombre="Juan",
            apellido="Perez",
            correo="juan_verif@test.com",
            id_cargo=self.cargo,
            valido=False,
            correo_verificado=False,
        )
        self.usuario.set_password(PASSWORD_VALIDA)
        self.usuario.save()

        from reservas.utils.email_verification import crear_verificacion

        self.verificacion = crear_verificacion(self.usuario)

        # Simula la sesión que registro() deja tras crear la cuenta - no hace
        # falta pasar por esa vista para este test.
        sesion = self.client.session
        sesion["verificacion_uid"] = self.usuario.pk
        sesion.save()

    def _intentar_codigo(self, codigo):
        return self.client.post(reverse("verificar_correo"), {"codigo": codigo})

    def test_codigo_correcto_deja_de_funcionar_tras_agotar_intentos(self):
        from reservas.models import VerificacionCorreo

        resp = None
        for _ in range(VerificacionCorreo.MAX_INTENTOS_CODIGO):
            resp = self._intentar_codigo("000000")  # nunca es el código real

        mensajes = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("Agotaste los intentos" in m for m in mensajes))

        self.verificacion.refresh_from_db()
        self.assertFalse(self.verificacion.esta_vigente())

        # El código real, el que se mandó por correo, ya no sirve: se
        # agotaron los intentos aunque falten minutos para que expire por
        # tiempo.
        self._intentar_codigo(self.verificacion.codigo)
        self.usuario.refresh_from_db()
        self.assertFalse(self.usuario.correo_verificado)

    def test_codigo_correcto_funciona_por_debajo_del_limite(self):
        from reservas.models import VerificacionCorreo

        for _ in range(VerificacionCorreo.MAX_INTENTOS_CODIGO - 1):
            self._intentar_codigo("000000")

        resp = self._intentar_codigo(self.verificacion.codigo)
        self.assertEqual(resp.status_code, 302)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.correo_verificado)


class TestEmailsUsanTemplates(TestCase):
    """
    Confirma que el registro y la recuperación de contraseña disparan el
    envío por la vía de templates (enviar_correo_templated_async), no la
    vieja de HTML hardcodeado en Python (enviar_correo_async). No se
    prueba el envío real: Q_CLUSTER no corre síncrono en tests, así que
    async_task solo encola una fila - alcanza con verificar que la llamada
    apunta al template correcto.
    """

    def setUp(self):
        self.cargo = Cargo.objects.create(nombre=Cargo.USUARIO, prioridad=3)

    def test_registro_encola_email_verification(self):
        with patch("reservas.utils.email_verification.async_task") as mock_async:
            resp = self.client.post(
                reverse("registro"),
                {
                    "nombre": "Ana",
                    "apellido": "Gomez",
                    "correo": "ana@test.com",
                    "id_cargo": self.cargo.pk,
                    "departamento": "TUL",
                    "contrasena": PASSWORD_VALIDA,
                    "confirmar_contrasena": PASSWORD_VALIDA,
                },
            )
        self.assertEqual(resp.status_code, 302)
        mock_async.assert_called_once()
        args = mock_async.call_args.args
        self.assertEqual(args[0], "reservas.tasks.enviar_correo_templated_async")
        self.assertEqual(args[2], "reservas/emails/email_verification")

    def test_solicitar_recuperacion_encola_password_recovery(self):
        usuario = Usuario(
            nombre="Juan",
            apellido="Perez",
            correo="juan@test.com",
            id_cargo=self.cargo,
            valido=True,
            correo_verificado=True,
        )
        usuario.set_password(PASSWORD_VALIDA)
        usuario.save()

        with patch("reservas.utils.password_recovery.async_task") as mock_async:
            resp = self.client.post(
                reverse("solicitar_recuperacion"), {"correo": "juan@test.com"}
            )
        self.assertEqual(resp.status_code, 302)
        mock_async.assert_called_once()
        args = mock_async.call_args.args
        self.assertEqual(args[0], "reservas.tasks.enviar_correo_templated_async")
        self.assertEqual(args[2], "reservas/emails/password_recovery")
