from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Tenant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("schema_name", models.CharField(db_index=True, max_length=63, unique=True)),
                ("name", models.CharField(max_length=200, verbose_name="Название клиники")),
                ("slug", models.SlugField(unique=True, verbose_name="Поддомен")),
                ("owner_email", models.EmailField(verbose_name="Email владельца")),
                ("phone", models.CharField(blank=True, max_length=30)),
                ("address", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"verbose_name": "Клиника (тенант)", "verbose_name_plural": "Клиники (тенанты)"},
        ),
        migrations.CreateModel(
            name="Domain",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("domain", models.CharField(db_index=True, max_length=253, unique=True)),
                ("is_primary", models.BooleanField(default=True, db_index=True)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="domains", to="tenants.tenant")),
            ],
            options={"verbose_name": "Домен", "verbose_name_plural": "Домены"},
        ),
        migrations.CreateModel(
            name="Subscription",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("plan", models.CharField(choices=[("trial", "Пробный"), ("basic", "Базовый"), ("pro", "Pro"), ("enterprise", "Enterprise")], default="trial", max_length=20)),
                ("started_at", models.DateField()),
                ("expired_at", models.DateField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("is_blocked", models.BooleanField(default=False)),
                ("monthly_price", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("notes", models.TextField(blank=True)),
                ("tenant", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="subscription", to="tenants.tenant")),
            ],
            options={"verbose_name": "Подписка", "verbose_name_plural": "Подписки"},
        ),
    ]
