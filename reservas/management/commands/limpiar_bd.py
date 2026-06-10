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
from reservas.models import Cargo, Usuario, Vehiculo, Ticket

class Command(BaseCommand):
    help = "Limpia los datos de la base de datos (Tickets, Usuarios, Vehículos) manteniendo la estructura de Cargos."

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Elimina también los Cargos maestros y todo el contenido de las tablas',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Iniciando limpieza de la base de datos..."))
        
        # Eliminar Tickets (tienen ForeignKey a Usuario y Vehiculo)
        count_tickets = Ticket.objects.all().delete()[0]
        self.stdout.write(f"  - {count_tickets} tickets eliminados")
        
        # Eliminar Usuarios
        count_usuarios = Usuario.objects.all().delete()[0]
        self.stdout.write(f"  - {count_usuarios} usuarios eliminados")
        
        # Eliminar Vehiculos
        count_vehiculos = Vehiculo.objects.all().delete()[0]
        self.stdout.write(f"  - {count_vehiculos} vehículos eliminados")
        
        if options['all']:
            # Eliminar Cargos
            count_cargos = Cargo.objects.all().delete()[0]
            self.stdout.write(f"  - {count_cargos} cargos eliminados")
            self.stdout.write(self.style.SUCCESS("\nLimpieza TOTAL completada (incluyendo cargos)."))
        else:
            self.stdout.write("  - Cargos preservados (datos maestros)")
            self.stdout.write(self.style.SUCCESS("\nLimpieza completada exitosamente. La base de datos está vacía (excepto por los Cargos)."))

if __name__ == "__main__":
    from django.core.management import execute_from_command_line
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    execute_from_command_line([sys.argv[0], "limpiar_bd", *sys.argv[1:]])
