"""Привязать входящие сообщения, оставшиеся без карточки пациента.

Зачем: привязка входящих искала пациента подстрокой по сырому полю phone.
Номера записывают по-разному, и «+996 553 552 595» не содержит подстроки
«553552595» — сообщение сохранялось с patient=None. Чат строится по
пациентам, поэтому такие сообщения не показывались НИГДЕ, хотя лежали в базе.

Сам поиск исправлен (find_patient_by_phone по индексированному phone_norm),
но уже накопленные сообщения остались висеть. Эта команда их привязывает.

Идемпотентна: трогает только записи с patient IS NULL.

    python manage.py relink_orphan_messages            # показать, что будет
    python manage.py relink_orphan_messages --apply    # применить
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Привязать входящие сообщения без карточки пациента (по номеру телефона)"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Применить изменения (без флага — только показать)")

    def handle(self, *args, **opts):
        from apps.notifications.models import WaMessage
        from apps.patients.models import find_patient_by_phone
        from apps.tenancy import unscoped

        apply = opts["apply"]
        linked = skipped = 0
        with unscoped():
            qs = WaMessage.all_clinics.filter(patient=None).exclude(phone="").order_by("id")
            total = qs.count()
            self.stdout.write(f"сообщений без карточки: {total}")
            for m in qs.iterator():
                p = find_patient_by_phone(m.phone)
                if p is None:
                    skipped += 1
                    continue
                linked += 1
                if apply:
                    m.patient = p
                    m.clinic = p.clinic
                    m.save(update_fields=["patient", "clinic"])
                elif linked <= 10:
                    self.stdout.write(f"  {m.phone} -> {p.full_name}")

        verb = "привязано" if apply else "будет привязано"
        self.stdout.write(self.style.SUCCESS(f"{verb}: {linked}, без совпадения: {skipped}"))
        if not apply:
            self.stdout.write("это был показ; для применения добавьте --apply")
