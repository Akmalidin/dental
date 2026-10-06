"""Разбор переписки ИИ-ассистента для пациентов: прогнать модель на истории
чата и показать, какие инструменты она вызывает и что они отвечают.
Ничего не записывает и не отправляет: запись/перенос/отмена/вызов
администратора только проверяются (validate_appointment), без изменений."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Сухой прогон ИИ-ассистента пациентов на истории чата"

    def add_arguments(self, parser):
        parser.add_argument("--clinic", type=int, required=True)
        parser.add_argument("--phone", required=True, help="номер или его последние цифры")
        parser.add_argument("--upto", type=int, default=0, help="id последнего сообщения истории (0 — все)")

    def handle(self, *args, **o):
        from unittest.mock import patch
        from apps.users.models import Clinic
        from apps.tenancy import set_current_clinic
        from apps.notifications import assistant as core
        from apps.notifications import patient_assistant as pa
        from apps.notifications.models import WaMessage
        clinic = Clinic.objects.get(pk=o["clinic"])
        set_current_clinic(clinic)
        qs = WaMessage.objects.filter(phone__endswith=o["phone"], channel="wa").order_by("-created_at")
        if o["upto"]:
            qs = qs.filter(pk__lte=o["upto"])
        msgs = list(qs[:pa.HISTORY])[::-1]
        if not msgs:
            self.stdout.write("нет сообщений")
            return
        address = msgs[-1].phone
        patient = next((m.patient for m in reversed(msgs) if m.patient_id), None) or pa._find_patient("wa", address)
        self.stdout.write("пациент: %s" % (patient and "%s (id %s)" % (patient.full_name, patient.pk)))
        for m in msgs:
            self.stdout.write("  %s %s %s" % (m.pk, "→" if m.direction == "out" else "←", (m.body or "")[:120]))

        def dry_book(ctx, doctor_id=None, start=None, duration_min=None, service_ids=None, full_name="", **_):
            from apps.services.models import Service
            doc, st = core._doctor(doctor_id), core._parse_start(start)
            if doc is None or st is None:
                return {"error": "Неверный врач или время"}
            services = list(Service.objects.filter(pk__in=service_ids or [], is_active=True))
            duration = int(duration_min or sum(s.duration for s in services) or 60)
            err = core.validate_appointment(doc, st, duration)
            if err:
                return {"error": err, "hint": "Предложи другое свободное время (free_slots)"}
            if ctx.patient is None and pa._find_patient(ctx.channel, ctx.address) is None and len(full_name.strip()) < 2:
                return {"error": "Пациент новый: спроси имя и фамилию одним вопросом, потом сразу запиши"}
            return {"ok": True, "dry_run": True, "doctor": doc.name, "start": start, "duration": duration}

        def dry_ok(ctx, **kw):
            return {"ok": True, "dry_run": True}
        handlers = dict(pa.HANDLERS, book_appointment=dry_book, reschedule_appointment=dry_ok,
                        cancel_appointment=dry_ok, call_admin=dry_ok)
        ctx = pa.PCtx(clinic, "wa", address, patient)
        history = [{"role": "user" if m.direction == "in" else "assistant", "text": pa._message_text(m)} for m in msgs]
        with patch.object(pa, "HANDLERS", handlers):
            reply = pa.run(ctx, history)
        for line in ctx.trace:
            self.stdout.write("tool: " + line)
        self.stdout.write("ответ: %s" % reply)
