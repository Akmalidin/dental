from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('treatments', '0020_treatment_needs_doctor_confirmation_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='treatmentcure',
            name='discount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5, verbose_name='Скидка %'),
        ),
    ]
