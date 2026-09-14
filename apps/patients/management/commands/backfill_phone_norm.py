"""Досчитать phone_norm у карточек, где он пустой.

Поле заполняется в Patient.save(), поэтому карточки, созданные в обход него
(массовый импорт, bulk_create), остались с пустым phone_norm. Поиск пациента
по номеру идёт именно по этому полю — для таких карточек входящие сообщения
не привязывались и не показывались в чате.

Идемпотентна: трогает только записи с пустым phone_norm и только это поле.

    python manage.py backfill_phone_norm            # показать, что будет
    python manage.py backfill_phone_norm --apply    # применить
"""
from django.core.management.base import BaseCommand
from django.db.models import Q


class Command(BaseCommand):
    help = "Заполнить пустой phone_norm у пациентов"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Применить изменения (без флага — только показать)")

    def handle(self, *args, **opts):
        from apps.patients.models import Patient, normalize_phone
        from apps.tenancy import unscoped

        apply = opts["apply"]
        filled = empty_phone = 0
        with unscoped():
            qs = (Patient.all_objects.filter(Q(phone_norm="") | Q(phone_norm__isnull=True))
                  .exclude(phone="").only("id", "phone", "phone_norm"))
            total = qs.count()
            self.stdout.write(f"карточек с пустым phone_norm: {total}")
            for p in qs.iterator():
                norm = normalize_phone(p.phone)
                if not norm:
                    empty_phone += 1
                    continue
                filled += 1
                if apply:
                    # update() вместо save(): не дёргаем сигналы и updated_at
                    # у карточек пациентов, меняем ровно одно служебное поле.
                    Patient.all_objects.filter(pk=p.pk).update(phone_norm=norm)
                elif filled <= 10:
                    self.stdout.write(f"  {p.phone!r} -> {norm}")

        verb = "заполнено" if apply else "будет заполнено"
        self.stdout.write(self.style.SUCCESS(
            f"{verb}: {filled}, номер непригоден: {empty_phone}"))
        if not apply:
            self.stdout.write("это был показ; для применения добавьте --apply")
