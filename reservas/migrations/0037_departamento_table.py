# Migración escrita a mano, no generada con makemigrations --dry-run tal
# cual: el autodetector propone un simple AlterField de CharField a
# ForeignKey, pero eso en Postgres es un ALTER COLUMN ... TYPE bigint sin
# forma de mapear "TUL"/"TUM"/etc. a un id numérico - falla o corrompe datos
# si ya hay usuarios con un departamento cargado.
#
# Pasos seguros, en orden:
#   1. Crear la tabla Departamento.
#   2. Sembrarla con los 8 códigos que antes eran choices hardcodeadas en
#      Usuario.DEPARTAMENTOS_CHOICES (idempotente con get_or_create, no
#      pisa nada si el admin ya los tocó de algún modo antes de correr esto).
#   3. Agregar un campo FK nuevo y temporal (usuario.departamento_nuevo).
#   4. Copiar cada Usuario.departamento (string viejo) al FK nuevo,
#      matcheando por nombre.
#   5. Borrar el CharField viejo.
#   6. Renombrar el FK nuevo a "departamento".

import django.db.models.deletion
from django.db import migrations, models

DEPARTAMENTOS_INICIALES = [
    "TUL",
    "TUM",
    "TUP",
    "TOUMRE",
    "IEM",
    "IQ",
    "ISI",
    "LAR",
]


def sembrar_departamentos(apps, schema_editor):
    Departamento = apps.get_model("reservas", "Departamento")
    for nombre in DEPARTAMENTOS_INICIALES:
        Departamento.objects.get_or_create(nombre=nombre)


def copiar_departamento_string_a_fk(apps, schema_editor):
    Usuario = apps.get_model("reservas", "Usuario")
    Departamento = apps.get_model("reservas", "Departamento")

    for usuario in Usuario.objects.exclude(departamento_viejo__isnull=True).exclude(
        departamento_viejo=""
    ):
        depto, _ = Departamento.objects.get_or_create(nombre=usuario.departamento_viejo)
        usuario.departamento_nuevo = depto
        usuario.save(update_fields=["departamento_nuevo"])


def copiar_fk_a_departamento_string(apps, schema_editor):
    """Reversa de copiar_departamento_string_a_fk, para poder migrar hacia atrás."""
    Usuario = apps.get_model("reservas", "Usuario")

    for usuario in Usuario.objects.exclude(departamento_nuevo__isnull=True):
        usuario.departamento_viejo = usuario.departamento_nuevo.nombre
        usuario.save(update_fields=["departamento_viejo"])


class Migration(migrations.Migration):

    dependencies = [
        ("reservas", "0036_verificacioncorreo_intentos_fallidos"),
    ]

    operations = [
        migrations.CreateModel(
            name="Departamento",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("nombre", models.CharField(max_length=20, unique=True)),
                ("descripcion", models.CharField(blank=True, max_length=100)),
            ],
            options={
                "verbose_name": "Departamento",
                "verbose_name_plural": "Departamentos",
                "ordering": ["nombre"],
            },
        ),
        migrations.RunPython(
            sembrar_departamentos,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RenameField(
            model_name="usuario",
            old_name="departamento",
            new_name="departamento_viejo",
        ),
        migrations.AddField(
            model_name="usuario",
            name="departamento_nuevo",
            field=models.ForeignKey(
                blank=True,
                help_text="Requerido si el cargo es Usuario",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="usuarios",
                to="reservas.departamento",
            ),
        ),
        migrations.RunPython(
            copiar_departamento_string_a_fk,
            reverse_code=copiar_fk_a_departamento_string,
        ),
        migrations.RemoveField(
            model_name="usuario",
            name="departamento_viejo",
        ),
        migrations.RenameField(
            model_name="usuario",
            old_name="departamento_nuevo",
            new_name="departamento",
        ),
    ]
