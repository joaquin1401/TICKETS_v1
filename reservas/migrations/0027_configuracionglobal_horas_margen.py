# Generated manually: add horas_margen_entre_reservas to ConfiguracionGlobal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reservas", "0026_vehiculo_patente_not_null"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracionglobal",
            name="horas_margen_entre_reservas",
            field=models.PositiveIntegerField(
                default=1,
                help_text="Horas de margen obligatorio entre la finalización de un ticket y el inicio del próximo para el mismo vehículo",
            ),
        ),
    ]
