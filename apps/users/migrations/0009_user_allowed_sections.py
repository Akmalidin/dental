from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0008_user_can_view_all_appointments'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='allowed_sections',
            field=models.JSONField(
                blank=True, default=None, null=True,
                help_text='Пусто (null) = все разделы по роли. Список ключей = только эти разделы.',
                verbose_name='Разрешённые разделы',
            ),
        ),
    ]
