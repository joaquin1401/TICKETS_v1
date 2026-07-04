from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.storage.fallback import FallbackStorage

from reservas.models import Cargo, Usuario, Vehiculo, Ticket, ConfiguracionGlobal
from reservas.tests.test_booking_rules import get_cargo
from reservas.views import inicio, detalle_ticket

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
            valido=True
        )
        self.admin = Usuario.objects.create(
            nombre="Admin",
            apellido="SEU",
            correo="admin@test.com",
            id_cargo=self.cargo_admin,
            valido=True
        )
        # Crear un chofer activo para que las validaciones de chofer disponible pasen
        self.chofer = Usuario.objects.create(
            nombre="Carlos",
            apellido="Chofer",
            correo="carlos@test.com",
            id_cargo=self.cargo_chofer,
            valido=True
        )
        self.vehiculo = Vehiculo.objects.create(
            marca="Toyota",
            modelo="Corolla",
            patente="XYZ789",
            cant_pasajeros=4,
            activo=True
        )
        self.ahora = timezone.now()

    def _prepare_request(self, request, usuario):
        # Set session middleware
        middleware = SessionMiddleware(lambda r: None)
        middleware.process_request(request)
        request.session["usuario_id"] = usuario.id
        request.session["es_admin"] = (usuario.id_cargo.prioridad == 0)
        request.session.save()
        
        # Set messages storage
        setattr(request, '_messages', FallbackStorage(request))

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
        ticket = Ticket.objects.filter(id_usuario=self.usuario, id_vehiculo=self.vehiculo).first()
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
            cant_pasajeros=2
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
            cant_pasajeros=2
        )
        
        request2 = self.factory.get(reverse("detalle_ticket", args=[ticket_cerca.id]))
        self._prepare_request(request2, self.usuario)
        
        response2 = detalle_ticket(request2, ticket_id=ticket_cerca.id)
        self.assertEqual(response2.status_code, 200)
        self.assertNotIn(b"Cancelar Ticket", response2.content)
