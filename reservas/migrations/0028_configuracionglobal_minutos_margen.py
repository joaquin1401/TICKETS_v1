# Generated manually: add minutos_margen_entre_reservas to ConfiguracionGlobal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reservas", "0027_configuracionglobal_horas_margen"),
    ]

    operations = [
        migrations.AddField(
            model_name="configuracionglobal",
            name="minutos_margen_entre_reservas",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Minutos adicionales de margen entre la finalización de un ticket y el inicio del próximo para el mismo vehículo",
            ),
        ),
    ]
