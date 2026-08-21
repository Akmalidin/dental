"""
Management command: python manage.py init_dev
Creates superadmin + demo clinic for local development.
"""
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Initialize dev data: superadmin + demo clinic"

    def handle(self, *args, **options):
        self._create_superadmin()

    def _create_superadmin(self):
        from apps.users.models import User, Role

        role, _ = Role.objects.get_or_create(name="superadmin")

        if User.objects.filter(login="admin").exists():
            self.stdout.write("  [skip] Superadmin already exists")
            return

        user = User(
            login="admin",
            email=getattr(settings, "SUPERADMIN_EMAIL", "akmalmadakimov6@gmail.com"),
            name="AKM SuperAdmin",
            is_staff=True,
            is_superuser=True,
        )
        user.set_password("7313")
        user.save()
        user.role = role
        user.save()
        self.stdout.write(self.style.SUCCESS("  [ok] Superadmin created: admin / 7313"))
