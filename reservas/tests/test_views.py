from datetime import timedelta

from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from reservas.models import Cargo, ConfiguracionGlobal, Ticket, Usuario, Vehiculo
from reservas.tests.test_booking_rules import get_cargo
from reservas.views import detalle_ticket, inicio


class TestReservasViews(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.cargo_usuario = get_cargo(Cargo.USUARIO, 3)
        self.cargo_admin = get_cargo(Cargo.ADMIN_SEU, 0)
        self.cargo_chofer = get_cargo(Cargo.CHOFER, 4)

        self.usuario = Usuario.objects.create(
            nombre="Juan",
            apellido="Perez",
            correo="juan@test.com",
            id_cargo=self.cargo_usuario,
            valido=True,
        )
        self.admin = Usuario.objects.create(
            nombre="Admin",
            apellido="SEU",
            correo="admin@test.com",
            id_cargo=self.cargo_admin,
            valido=True,
        )
        # Crear un chofer activo para que las validaciones de chofer disponible pasen
        self.chofer = Usuario.objects.create(
            nombre="Carlos",
            apellido="Chofer",
            correo="carlos@test.com",
            id_cargo=self.cargo_chofer,
            valido=True,
        )
        self.vehiculo = Vehiculo.objects.create(
            marca="Toyota",
            modelo="Corolla",
            patente="XYZ789",
            cant_pasajeros=4,
            activo=True,
        )
        self.ahora = timezone.now()

    def _prepare_request(self, request, usuario):
        # Set session middleware
        middleware = SessionMiddleware(lambda r: None)
        middleware.process_request(request)
        request.session["usuario_id"] = usuario.id
        request.session["es_admin"] = usuario.id_cargo.prioridad == 0
        request.session.save()

        # Set messages storage
        request._messages = FallbackStorage(request)

    def test_inicio_view_get(self):
        """La vista de inicio debe cargar correctamente con GET."""
        request = self.factory.get(reverse("inicio"))
        self._prepare_request(request, self.usuario)

        response = inicio(request)
        self.assertEqual(response.status_code, 200)

    def test_reserva_exitosa_via_post(self):
        """Crear una reserva válida mediante POST en /inicio/ debe ser exitoso y redirigir."""
        # Una reserva a los 4 días en el futuro (cumple los 3 días mínimos de la config)
        inicio_reserva = self.ahora + timedelta(days=4)
        fin_reserva = inicio_reserva + timedelta(hours=2)

        post_data = {
            "id_vehiculo": self.vehiculo.id,
            "destino": "Sede Central",
            "cant_pasajeros": 2,
            "descripcion": "Viaje institucional",
            "hora_inicio": inicio_reserva.strftime("%Y-%m-%dT%H:%M"),
            "hora_fin": fin_reserva.strftime("%Y-%m-%dT%H:%M"),
        }

        request = self.factory.post(reverse("inicio"), data=post_data)
        self._prepare_request(request, self.usuario)

        response = inicio(request)

        # Debe redirigir (302) a historial tras creación exitosa
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("historial"))

        # Verificar que el ticket existe y está aprobado
        ticket = Ticket.objects.filter(
            id_usuario=self.usuario, id_vehiculo=self.vehiculo
        ).first()
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.estado, Ticket.ESTADO_APROBADO)

    def test_reserva_bloqueda_por_anticipacion_via_post(self):
        """La reserva debe fallar (retornar 200 con la página) si no cumple la antelación mínima."""
        # Una reserva a los 2 días (menos de los 3 días por defecto)
        inicio_reserva = self.ahora + timedelta(days=2)
        fin_reserva = inicio_reserva + timedelta(hours=2)

        post_data = {
            "id_vehiculo": self.vehiculo.id,
            "destino": "Sede Central",
            "cant_pasajeros": 2,
            "descripcion": "Viaje urgente",
            "hora_inicio": inicio_reserva.strftime("%Y-%m-%dT%H:%M"),
            "hora_fin": fin_reserva.strftime("%Y-%m-%dT%H:%M"),
        }

        request = self.factory.post(reverse("inicio"), data=post_data)
        self._prepare_request(request, self.usuario)

        response = inicio(request)

        # Al fallar, se vuelve a renderizar el formulario (status 200)
        self.assertEqual(response.status_code, 200)

    def test_cancellation_button_visibility_in_details_view(self):
        """La visibilidad del botón de cancelación en detalle_ticket debe depender de la configuración."""
        # Configurar cancelación a 5 días
        config = ConfiguracionGlobal.get_solo()
        config.dias_anticipacion_cancelacion = 5
        config.save()

        # Caso 1: Ticket a los 6 días de distancia -> puede_cancelar debe ser True (el botón "Cancelar Ticket" se renderiza)
        inicio_lejos = self.ahora + timedelta(days=6)
        ticket_lejos = Ticket.objects.create(
            id_usuario=self.usuario,
            id_vehiculo=self.vehiculo,
            hora_inicio=inicio_lejos,
            hora_fin=inicio_lejos + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO,
            destino="Test",
            cant_pasajeros=2,
        )

        request = self.factory.get(reverse("detalle_ticket", args=[ticket_lejos.id]))
        self._prepare_request(request, self.usuario)

        response = detalle_ticket(request, ticket_id=ticket_lejos.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Cancelar Ticket", response.content)

        # Caso 2: Ticket a los 4 días de distancia -> puede_cancelar debe ser False (el botón no se renderiza)
        inicio_cerca = self.ahora + timedelta(days=4)
        ticket_cerca = Ticket.objects.create(
            id_usuario=self.usuario,
            id_vehiculo=self.vehiculo,
            hora_inicio=inicio_cerca,
            hora_fin=inicio_cerca + timedelta(hours=2),
            estado=Ticket.ESTADO_APROBADO,
            destino="Test",
            cant_pasajeros=2,
        )

        request2 = self.factory.get(reverse("detalle_ticket", args=[ticket_cerca.id]))
        self._prepare_request(request2, self.usuario)

        response2 = detalle_ticket(request2, ticket_id=ticket_cerca.id)
        self.assertEqual(response2.status_code, 200)
        self.assertNotIn(b"Cancelar Ticket", response2.content)

    def test_timeline_top_px_usa_hora_local_no_utc(self):
        """El posicionamiento del bloque del timeline (top_px/height_px) debe
        calcularse con la hora LOCAL, igual que el texto "HH:MM → HH:MM" que
        muestra el template."""
        fecha = (self.ahora + timedelta(days=1)).date()
        # 08:00 -> 10:00 hora LOCAL (Argentina); en UTC sería 11:00 -> 13:00.
        hora_inicio_local = timezone.make_aware(
            timezone.datetime.combine(fecha, timezone.datetime.min.time())
            + timedelta(hours=8)
        )
        hora_fin_local = hora_inicio_local + timedelta(hours=2)

        Ticket.objects.create(
            id_usuario=self.usuario,
            id_vehiculo=self.vehiculo,
            hora_inicio=hora_inicio_local,
            hora_fin=hora_fin_local,
            estado=Ticket.ESTADO_APROBADO,
            destino="Test",
            cant_pasajeros=2,
        )

        sesion = self.client.session
        sesion["usuario_id"] = self.usuario.pk
        sesion["es_admin"] = False
        sesion.save()

        response = self.client.get(
            reverse("inicio"),
            {
                "vehiculo": self.vehiculo.pk,
                "anio": fecha.year,
                "mes": fecha.month,
                "dia": fecha.day,
            },
        )
        self.assertEqual(response.status_code, 200)

        tickets_dia = response.context["tickets_dia"]
        self.assertEqual(len(tickets_dia), 1)
        ticket_ctx = tickets_dia[0]

        # top: 0px == 06:00 (inicio de la grilla). 08:00 local -> top_px = 120.
        self.assertEqual(ticket_ctx.top_px, 120)
        # 2 horas de duración -> 120px de alto.
        self.assertEqual(ticket_ctx.height_px, 120)

        # El texto renderizado debe decir "08:00 → 10:00", coincidiendo con el bloque.
        self.assertContains(response, "08:00 → 10:00")
