"""
Tests de Departamento: modelo, CRUD desde configuracion_global() y su uso
en RegistroForm.

Departamento reemplazó a Usuario.DEPARTAMENTOS_CHOICES (una lista fija
hardcodeada en el modelo) por una tabla real, para que el admin pueda
agregar/editar/eliminar departamentos desde el panel de Configuración
Global sin tocar código (ver migración 0037_departamento_table).

Los nombres de prueba usan el prefijo "ZZTEST" a propósito: la migración
0037 siembra los 8 departamentos originales (TUL, TUM, TUP, TOUMRE, IEM,
IQ, ISI, LAR) en cualquier BD de test, así que usar esos mismos nombres
acá chocaría con "nombre" unique.
"""

from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse

from reservas.models import Cargo, Departamento, Usuario


def get_cargo(nombre, prioridad):
    cargo, created = Cargo.objects.get_or_create(
        nombre=nombre, defaults={"prioridad": prioridad}
    )
    if not created and cargo.prioridad != prioridad:
        cargo.prioridad = prioridad
        cargo.save()
    return cargo


class TestDepartamentoModelo(TestCase):
    def test_str_devuelve_el_nombre(self):
        depto = Departamento.objects.create(nombre="ZZTEST-STR")
        self.assertEqual(str(depto), "ZZTEST-STR")

    def test_no_se_puede_eliminar_un_departamento_en_uso(self):
        """
        on_delete=PROTECT: si algún Usuario tiene este departamento asignado,
        Django debe bloquear el delete en vez de dejar usuarios "huérfanos"
        o, peor, borrar en cascada.
        """
        cargo = get_cargo(Cargo.USUARIO, 3)
        depto = Departamento.objects.create(nombre="ZZTEST-PROTECT")
        Usuario.objects.create(
            nombre="Juan",
            apellido="Perez",
            correo="juan_depto@test.com",
            id_cargo=cargo,
            departamento=depto,
            valido=True,
        )

        with self.assertRaises(ProtectedError):
            depto.delete()

    def test_se_puede_eliminar_un_departamento_sin_uso(self):
        depto = Departamento.objects.create(nombre="ZZTEST-SINUSO")
        depto.delete()
        self.assertFalse(Departamento.objects.filter(nombre="ZZTEST-SINUSO").exists())


class TestDepartamentoCRUDAdmin(TestCase):
    """CRUD desde el panel de Configuración Global (solo admin)."""

    def setUp(self):
        self.cargo_admin = get_cargo(Cargo.ADMIN_SEU, 0)
        self.admin = Usuario.objects.create(
            nombre="Admin",
            apellido="SEU",
            correo="admin_depto@test.com",
            id_cargo=self.cargo_admin,
            valido=True,
            correo_verificado=True,
        )
        sesion = self.client.session
        sesion["usuario_id"] = self.admin.pk
        sesion["es_admin"] = True
        sesion.save()

    def _post(self, data):
        return self.client.post(reverse("configuracion_global"), data)

    def test_agregar_departamento(self):
        resp = self._post(
            {
                "action": "add_departamento",
                "nombre_departamento": "ZZTEST-NUEVO",
                "descripcion_departamento": "Departamento de prueba",
            }
        )
        self.assertEqual(resp.status_code, 302)
        depto = Departamento.objects.get(nombre="ZZTEST-NUEVO")
        self.assertEqual(depto.descripcion, "Departamento de prueba")

    def test_no_se_puede_agregar_nombre_duplicado(self):
        Departamento.objects.create(nombre="ZZTEST-DUP")
        self._post({"action": "add_departamento", "nombre_departamento": "ZZTEST-DUP"})
        # No se creó un segundo - sigue habiendo exactamente uno.
        self.assertEqual(Departamento.objects.filter(nombre="ZZTEST-DUP").count(), 1)

    def test_no_se_puede_agregar_sin_nombre(self):
        total_antes = Departamento.objects.count()
        self._post({"action": "add_departamento", "nombre_departamento": ""})
        self.assertEqual(Departamento.objects.count(), total_antes)

    def test_editar_departamento(self):
        depto = Departamento.objects.create(nombre="ZZTEST-EDIT", descripcion="vieja")
        resp = self._post(
            {
                "action": "edit_departamento",
                "departamento_id": depto.pk,
                "nombre_departamento": "ZZTEST-EDIT-NUEVO",
                "descripcion_departamento": "nueva",
            }
        )
        self.assertEqual(resp.status_code, 302)
        depto.refresh_from_db()
        self.assertEqual(depto.nombre, "ZZTEST-EDIT-NUEVO")
        self.assertEqual(depto.descripcion, "nueva")

    def test_editar_no_puede_dejar_nombre_duplicado_de_otro(self):
        Departamento.objects.create(nombre="ZZTEST-A")
        depto_b = Departamento.objects.create(nombre="ZZTEST-B")
        self._post(
            {
                "action": "edit_departamento",
                "departamento_id": depto_b.pk,
                "nombre_departamento": "ZZTEST-A",
            }
        )
        depto_b.refresh_from_db()
        self.assertEqual(
            depto_b.nombre, "ZZTEST-B", "no debería haberse renombrado a ZZTEST-A"
        )

    def test_eliminar_departamento_sin_uso(self):
        depto = Departamento.objects.create(nombre="ZZTEST-DELETE")
        self._post({"action": "delete_departamento", "departamento_id": depto.pk})
        self.assertFalse(Departamento.objects.filter(pk=depto.pk).exists())

    def test_eliminar_departamento_en_uso_no_lo_borra_y_avisa(self):
        cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        depto = Departamento.objects.create(nombre="ZZTEST-ENUSO")
        Usuario.objects.create(
            nombre="Juan",
            apellido="Perez",
            correo="juan_en_uso@test.com",
            id_cargo=cargo_usuario,
            departamento=depto,
            valido=True,
        )

        resp = self._post(
            {"action": "delete_departamento", "departamento_id": depto.pk}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Departamento.objects.filter(pk=depto.pk).exists())

        # El mensaje de error se agrega antes del redirect - se lee en la
        # página de destino, como cualquier messages.error() de Django.
        resp_final = self.client.get(reverse("configuracion_global"))
        mensajes = [str(m) for m in resp_final.context["messages"]]
        self.assertTrue(any("no se puede eliminar" in m.lower() for m in mensajes))

    def test_no_admin_no_puede_gestionar_departamentos(self):
        cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        usuario = Usuario.objects.create(
            nombre="Juan",
            apellido="Perez",
            correo="no_admin@test.com",
            id_cargo=cargo_usuario,
            valido=True,
        )
        sesion = self.client.session
        sesion["usuario_id"] = usuario.pk
        sesion["es_admin"] = False
        sesion.save()

        resp = self._post(
            {"action": "add_departamento", "nombre_departamento": "ZZTEST-NOADMIN"}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("inicio"))
        self.assertFalse(Departamento.objects.filter(nombre="ZZTEST-NOADMIN").exists())


class TestRegistroFormUsaDepartamento(TestCase):
    """
    RegistroForm.departamento pasó de CharField(choices=...) a
    ModelChoiceField (automático vía ModelForm, al cambiar el campo del
    modelo a ForeignKey) - confirma que el registro real sigue funcionando.
    """

    def setUp(self):
        self.cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        # get_or_create, no create: la migración 0037 ya siembra TUL.
        self.departamento, _ = Departamento.objects.get_or_create(nombre="TUL")

    def test_registro_con_departamento_valido(self):
        resp = self.client.post(
            reverse("registro"),
            {
                "nombre": "Ana",
                "apellido": "Gomez",
                "correo": "ana_depto_form@test.com",
                "id_cargo": self.cargo_usuario.pk,
                "departamento": self.departamento.pk,
                "contrasena": "Trayecto-Vehiculo-91",
                "confirmar_contrasena": "Trayecto-Vehiculo-91",
            },
        )
        self.assertEqual(resp.status_code, 302)
        usuario = Usuario.objects.get(correo="ana_depto_form@test.com")
        self.assertEqual(usuario.departamento, self.departamento)

    def test_registro_rechaza_id_de_departamento_inexistente(self):
        resp = self.client.post(
            reverse("registro"),
            {
                "nombre": "Ana",
                "apellido": "Gomez",
                "correo": "ana_depto_invalido@test.com",
                "id_cargo": self.cargo_usuario.pk,
                "departamento": 999999,
                "contrasena": "Trayecto-Vehiculo-91",
                "confirmar_contrasena": "Trayecto-Vehiculo-91",
            },
        )
        self.assertEqual(
            resp.status_code, 200, "debe re-renderizar con error, no crear"
        )
        self.assertFalse(
            Usuario.objects.filter(correo="ana_depto_invalido@test.com").exists()
        )
