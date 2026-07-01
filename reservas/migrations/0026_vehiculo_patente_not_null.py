# Generated manually: make patente required (non-nullable, non-blankable)
# Since patente is now a required field on Vehiculo

from django.db import migrations, models


def set_default_patente(apps, schema_editor):
    """Set a default patente for any vehicles that have NULL or blank patente."""
    Vehiculo = apps.get_model("reservas", "Vehiculo")
    Vehiculo.objects.filter(patente__isnull=True).update(patente="S/P")
    Vehiculo.objects.filter(patente__exact="").update(patente="S/P")


class Migration(migrations.Migration):

    dependencies = [
        ("reservas", "0025_feriado"),
    ]

    operations = [
        migrations.RunPython(set_default_patente, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="vehiculo",
            name="patente",
            field=models.CharField(max_length=20, unique=True),
        ),
    ]
