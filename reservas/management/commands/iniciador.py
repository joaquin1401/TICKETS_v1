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

from reservas.models import Cargo, Usuario


class Command(BaseCommand):
    help = (
        "Crea los 7 cargos del sistema (si no existen) y un usuario "
        "administrador SEU (si no existe). No borra nada de lo que ya haya "
        "en la base."
    )

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Creando cargos..."))

        # Los 7 cargos del sistema, con la misma jerarquía que usa
        # poblar_bd.py en el resto del proyecto (menor número = más
        # prioridad). Sin esto, RegistroForm arma su dropdown de "Cargo"
        # con Cargo.objects.exclude(prioridad=0): con un solo cargo
        # (Administrador SEU, prioridad 0) ese desplegable queda vacío y
        # nadie puede autoregistrarse.
        cargos_config = [
            (Cargo.ADMIN_SEU, 0),
            (Cargo.DECANO, 1),
            (Cargo.VICEDECANO, 1),
            (Cargo.SECRETARIO, 2),
            (Cargo.SUBSECRETARIO, 2),
            (Cargo.USUARIO, 3),
            (Cargo.CHOFER, 4),
        ]
        cargos = {}
        for nombre, prioridad in cargos_config:
            cargo, created = Cargo.objects.get_or_create(
                nombre=nombre, defaults={"prioridad": prioridad}
            )
            cargos[nombre] = cargo
            estado = "creado" if created else "ya existía"
            self.stdout.write(f"  - {nombre} (prioridad {prioridad}) {estado}.")

        cargo_admin = cargos[Cargo.ADMIN_SEU]

        self.stdout.write(self.style.WARNING("\nCreando usuario administrador SEU..."))

        # `correo` es unique en Usuario, así que get_or_create alcanza para
        # que correr este comando de nuevo no explote ni pise al usuario si
        # ya existe.
        correo = "Bissonsebastian@gmail.com"
        nombre = "Sebastian"
        apellido = "Bisson"
        password = "test123456"

        admin_user, created = Usuario.objects.get_or_create(
            correo=correo,
            defaults={
                "id_cargo": cargo_admin,
                "nombre": nombre,
                "apellido": apellido,
                "valido": True,
                "correo_verificado": True,
                "rechazado": False,
                "departamento": None,
            },
        )

        if created:
            admin_user.set_password(password)
            admin_user.save()
            self.stdout.write(
                self.style.SUCCESS("\nUsuario administrador creado exitosamente:")
            )
            self.stdout.write(f"  - Correo: {correo}")
            self.stdout.write(f"  - Contraseña: {password}")
            self.stdout.write(f"  - Nombre completo: {nombre} {apellido}")
            self.stdout.write(f"  - Cargo: {cargo_admin.nombre}")
        else:
            self.stdout.write(f"  - Usuario administrador ya existía ({correo}).")

        self.stdout.write(
            self.style.SUCCESS("\n¡Proceso finalizado! Ya podés ingresar al sistema.")
        )


if __name__ == "__main__":
    from django.core.management import execute_from_command_line

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    execute_from_command_line([sys.argv[0], "iniciador", *sys.argv[1:]])
