from django.db import migrations, models
import django.db.models.deletion
import django.contrib.auth.models
import django.contrib.auth.validators
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="Branch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200, verbose_name="Название")),
                ("address", models.CharField(max_length=500, verbose_name="Адрес")),
                ("phone", models.CharField(max_length=30, verbose_name="Телефон")),
                ("is_main", models.BooleanField(default=False, verbose_name="Главный филиал")),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"verbose_name": "Филиал", "verbose_name_plural": "Филиалы", "ordering": ["-is_main", "name"]},
        ),
        migrations.CreateModel(
            name="Role",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(choices=[("superadmin", "Суперадмин AKM SOFT"), ("admin_main", "Главный администратор"), ("admin", "Администратор"), ("doctor", "Доктор"), ("nurse", "Медсестра")], max_length=50, unique=True, verbose_name="Роль")),
                ("permissions", models.ManyToManyField(blank=True, to="auth.permission", verbose_name="Права доступа")),
            ],
            options={"verbose_name": "Роль", "verbose_name_plural": "Роли"},
        ),
        migrations.CreateModel(
            name="User",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("is_superuser", models.BooleanField(default=False)),
                ("first_name", models.CharField(blank=True, max_length=150, verbose_name="first name")),
                ("last_name", models.CharField(blank=True, max_length=150, verbose_name="last name")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="email address")),
                ("is_staff", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("date_joined", models.DateTimeField(default=django.utils.timezone.now)),
                ("login", models.CharField(max_length=150, unique=True, verbose_name="Логин")),
                ("name", models.CharField(max_length=200, verbose_name="Имя")),
                ("phone", models.CharField(blank=True, max_length=30, verbose_name="Телефон")),
                ("avatar", models.ImageField(blank=True, null=True, upload_to="avatars/", verbose_name="Аватар")),
                ("telegram_id", models.BigIntegerField(blank=True, null=True, verbose_name="Telegram ID")),
                ("branches", models.ManyToManyField(blank=True, related_name="users", to="users.branch", verbose_name="Филиалы")),
                ("groups", models.ManyToManyField(blank=True, related_name="user_set", related_query_name="user", to="auth.group")),
                ("role", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="users", to="users.role", verbose_name="Роль")),
                ("user_permissions", models.ManyToManyField(blank=True, related_name="user_set", related_query_name="user", to="auth.permission")),
            ],
            options={"verbose_name": "Пользователь", "verbose_name_plural": "Пользователи"},
            managers=[("objects", django.contrib.auth.models.UserManager())],
        ),
        migrations.CreateModel(
            name="UserActivity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("action", models.CharField(choices=[("login", "Вход"), ("logout", "Выход"), ("create", "Создание"), ("update", "Изменение"), ("delete", "Удаление"), ("view", "Просмотр")], max_length=20)),
                ("model_name", models.CharField(blank=True, max_length=100)),
                ("object_id", models.CharField(blank=True, max_length=50)),
                ("description", models.TextField(blank=True)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="activities", to="users.user")),
            ],
            options={"verbose_name": "Действие пользователя", "verbose_name_plural": "Действия пользователей", "ordering": ["-created_at"]},
        ),
    ]
