import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()

from django.core.management.base import BaseCommand
from django.core.management import call_command
from reservas.models import Cargo, Ticket, Usuario, Vehiculo, IntentoLoginFallido

class Command(BaseCommand):
    help = "Elimina toda la base de datos (tickets, usuarios, vehículos y cargos) y crea un usuario administrador SEU."

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Eliminando datos existentes..."))
        
        # Eliminar todos los datos de las aplicaciones en orden
        count_tickets = Ticket.objects.all().delete()[0]
        count_usuarios = Usuario.objects.all().delete()[0]
        count_vehiculos = Vehiculo.objects.all().delete()[0]
        count_intentos = IntentoLoginFallido.objects.all().delete()[0]
        count_cargos = Cargo.objects.all().delete()[0]
        
        self.stdout.write(f"  - {count_tickets} tickets eliminados")
        self.stdout.write(f"  - {count_usuarios} usuarios eliminados")
        self.stdout.write(f"  - {count_vehiculos} vehículos eliminados")
        self.stdout.write(f"  - {count_intentos} intentos de login eliminados")
        self.stdout.write(f"  - {count_cargos} cargos eliminados")
        self.stdout.write(self.style.SUCCESS("Base de datos limpia."))

        self.stdout.write(self.style.WARNING("\nCreando usuario administrador SEU..."))
        
        # Crear cargo Administrador SEU
        cargo_admin, created = Cargo.objects.get_or_create(
            nombre="Administrador SEU",
            defaults={"prioridad": 0}
        )
        if created:
            self.stdout.write("  - Cargo 'Administrador SEU' creado con prioridad 0.")
        else:
            self.stdout.write("  - Cargo 'Administrador SEU' ya existía.")

        # Crear el usuario
        correo = "Bissonsebastian@gmail.com"
        nombre = "Sebastian"
        apellido = "Bisson"
        password = "test123456"

        admin_user = Usuario(
            id_cargo=cargo_admin,
            nombre=nombre,
            apellido=apellido,
            correo=correo,
            valido=True,
            correo_verificado=True,
            rechazado=False,
            departamento=None
        )
        admin_user.set_password(password)
        admin_user.save()
        
        self.stdout.write(self.style.SUCCESS(f"\nUsuario administrador creado exitosamente:"))
        self.stdout.write(f"  - Correo: {correo}")
        self.stdout.write(f"  - Contraseña: {password}")
        self.stdout.write(f"  - Nombre completo: {nombre} {apellido}")
        self.stdout.write(f"  - Cargo: {cargo_admin.nombre}")
        self.stdout.write(self.style.SUCCESS("\n¡Proceso finalizado! Ya podés ingresar al sistema."))

if __name__ == "__main__":
    from django.core.management import execute_from_command_line
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    execute_from_command_line([sys.argv[0], "iniciador", *sys.argv[1:]])
