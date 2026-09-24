from unittest.mock import patch

from django.test import TestCase, Client, override_settings

from apps.users.models import User, Role, Clinic, Branch
from apps.settings_clinic.models import ClinicSettings


class TgWebhookSecretTestCase(TestCase):
    """Аудит безопасности: tg_webhook раньше не проверял, что запрос реально
    пришёл от Telegram — clinic_slug в адресе публичный (виден в
    <slug>.stom.asia), сам по себе секретом не является. Кто угодно мог
    слать поддельные апдейты на реальный вебхук клиники (например, привязать
    чужой chat_id к карточке пациента по номеру телефона — см.
    _tg_link_by_phone). Теперь Telegram обязан присылать секрет вебхука в
    заголовке X-Telegram-Bot-Api-Secret-Token."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника TG", slug="tg-clinic")
        Branch.objects.create(name="Гл. филиал", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.cs = ClinicSettings.objects.create(
            clinic=self.clinic, name=self.clinic.name,
            telegram_bot_token="123:ABC", telegram_webhook_secret="s3cr3t-token-value",
        )
        self.client = Client()
        self.url = f"/notifications/tg-webhook/{self.clinic.slug}/"

    def test_request_without_secret_header_rejected(self):
        resp = self.client.post(self.url, data="{}", content_type="application/json")
        self.assertEqual(resp.status_code, 403)

    def test_request_with_wrong_secret_rejected(self):
        resp = self.client.post(
            self.url, data="{}", content_type="application/json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="wrong-guess",
        )
        self.assertEqual(resp.status_code, 403)

    def test_request_with_correct_secret_accepted(self):
        with patch("apps.notifications.views._tg_handle_update"):
            resp = self.client.post(
                self.url, data="{}", content_type="application/json",
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="s3cr3t-token-value",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

    def test_unknown_clinic_slug_404(self):
        resp = self.client.post(
            "/notifications/tg-webhook/does-not-exist/", data="{}", content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_no_secret_configured_yet_is_backward_compatible(self):
        """Клиника, подключившая бота ДО этого фикса, ещё без секрета
        (заполняется command backfill_telegram_webhook_secrets при деплое) —
        запрос не должен блокироваться, иначе уже работающий бот сломается
        сразу после деплоя, до отработки ретрофита."""
        self.cs.telegram_webhook_secret = ""
        self.cs.save(update_fields=["telegram_webhook_secret"])
        with patch("apps.notifications.views._tg_handle_update"):
            resp = self.client.post(self.url, data="{}", content_type="application/json")
        self.assertEqual(resp.status_code, 200)

    def test_get_not_allowed(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)


class TgConnectSecretTestCase(TestCase):
    """При сохранении/смене токена бота tg_connect должен выпускать секрет
    вебхука и передавать его в setWebhook."""

    def setUp(self):
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.clinic = Clinic.objects.create(name="Клиника Connect", slug="tg-connect-clinic")
        Branch.objects.create(name="Гл. филиал", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.director = User.objects.create(
            login="tgc_director", name="Директор TG", email="tgcd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

    @patch("apps.notifications.telegram.tg_set_webhook")
    @patch("apps.notifications.telegram.tg_get_me")
    def test_save_token_generates_secret_and_registers_webhook(self, mock_get_me, mock_set_webhook):
        mock_get_me.return_value = {"ok": True, "result": {"username": "test_bot"}}
        mock_set_webhook.return_value = {"ok": True}

        resp = self.client.post("/notifications/tg-connect/", {
            "telegram_enabled": "on", "telegram_bot_token": "123:NEWTOKEN",
        })
        self.assertEqual(resp.status_code, 302)

        cs = ClinicSettings.objects.get(clinic=self.clinic)
        self.assertTrue(cs.telegram_webhook_secret)
        mock_set_webhook.assert_called_once()
        _args, kwargs = mock_set_webhook.call_args
        self.assertEqual(kwargs.get("secret_token"), cs.telegram_webhook_secret)

    @patch("apps.notifications.telegram.tg_set_webhook")
    @patch("apps.notifications.telegram.tg_get_me")
    def test_changing_token_reissues_secret(self, mock_get_me, mock_set_webhook):
        mock_get_me.return_value = {"ok": True, "result": {"username": "test_bot"}}
        mock_set_webhook.return_value = {"ok": True}

        cs = ClinicSettings.objects.create(
            clinic=self.clinic, name=self.clinic.name,
            telegram_bot_token="123:OLD", telegram_webhook_secret="old-secret-value",
        )
        self.client.post("/notifications/tg-connect/", {
            "telegram_enabled": "on", "telegram_bot_token": "123:NEWTOKEN",
        })
        cs.refresh_from_db()
        self.assertNotEqual(cs.telegram_webhook_secret, "old-secret-value")
        self.assertTrue(cs.telegram_webhook_secret)


class TgInboxLoggingTestCase(TestCase):
    """До этого фикса /start, «поделился номером» и нажатия кнопок меню
    самообслуживания обрабатывались ботом (пациенту реально приходил ответ
    в Telegram), но не создавали WaMessage — переписка не попадала в общий
    список «Мессенджеры» (apps.users.views грузит только WaMessage с
    привязанным пациентом), хотя пациент уже привязан и бот ему отвечает —
    ровно то, что сообщили: бот работает, а в CRM переписок нет."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника TG Inbox", slug="tg-inbox-clinic")
        Branch.objects.create(name="Гл. филиал", address="-", phone="0", is_main=True, clinic=self.clinic)
        ClinicSettings.objects.create(
            clinic=self.clinic, name=self.clinic.name, telegram_bot_token="123:ABC",
        )
        from apps.patients.models import Patient
        self.patient = Patient.objects.create(
            first_name="Акмал", last_name="Тест", phone="+996553565674", clinic=self.clinic,
        )

    def _send(self, message):
        import json
        from apps.notifications.views import _tg_handle_update
        with patch("apps.notifications.telegram._call", return_value={"ok": True, "result": {"message_id": 1}}):
            _tg_handle_update(json.dumps({"message": message}).encode(), self.clinic.slug)

    def test_contact_share_links_patient_and_logs_conversation(self):
        self._send({"chat": {"id": 555}, "contact": {"phone_number": "+996553565674"}})
        from apps.notifications.models import WaMessage
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.telegram_chat_id, 555)
        m = WaMessage.objects.get()
        self.assertEqual(m.patient_id, self.patient.pk)
        self.assertEqual(m.channel, "tg")

    def test_menu_button_press_is_logged(self):
        self.patient.telegram_chat_id = 555
        self.patient.save(update_fields=["telegram_chat_id"])
        from apps.notifications.telegram import BTN_MY_DEBT
        self._send({"chat": {"id": 555}, "text": BTN_MY_DEBT})
        from apps.notifications.models import WaMessage
        m = WaMessage.objects.get()
        self.assertEqual(m.patient_id, self.patient.pk)
        self.assertEqual(m.body, BTN_MY_DEBT)

    def test_typed_phone_number_link_is_logged(self):
        self._send({"chat": {"id": 555}, "text": "+996553565674"})
        from apps.notifications.models import WaMessage
        m = WaMessage.objects.get()
        self.assertEqual(m.patient_id, self.patient.pk)

    def test_regular_text_message_still_logged_as_before(self):
        self.patient.telegram_chat_id = 555
        self.patient.save(update_fields=["telegram_chat_id"])
        self._send({"chat": {"id": 555}, "text": "Здравствуйте, можно перенести приём?"})
        from apps.notifications.models import WaMessage
        m = WaMessage.objects.get()
        self.assertEqual(m.patient_id, self.patient.pk)
        self.assertEqual(m.body, "Здравствуйте, можно перенести приём?")


class BackfillTelegramWebhookSecretsCommandTestCase(TestCase):
    """apps.notifications.management.commands.backfill_telegram_webhook_secrets
    — вызывается из deploy/update.sh при каждом деплое, выпускает секрет
    вебхука для клиник, подключивших бота ДО этого фикса безопасности."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника Backfill", slug="tg-backfill-clinic")

    def _run(self):
        from django.core.management import call_command
        call_command("backfill_telegram_webhook_secrets")

    @patch("apps.notifications.telegram.tg_set_webhook")
    @patch("apps.notifications.telegram.tg_get_webhook_info")
    def test_issues_secret_for_clinic_missing_one(self, mock_info, mock_set_webhook):
        cs = ClinicSettings.objects.create(
            clinic=self.clinic, name=self.clinic.name,
            telegram_bot_token="123:OLDBOT", telegram_webhook_secret="",
        )
        mock_info.return_value = {"ok": True, "result": {
            "url": "https://denta.tw1.ru/notifications/tg-webhook/tg-backfill-clinic/",
        }}
        mock_set_webhook.return_value = {"ok": True}

        self._run()

        cs.refresh_from_db()
        self.assertTrue(cs.telegram_webhook_secret)
        mock_set_webhook.assert_called_once()
        args, kwargs = mock_set_webhook.call_args
        self.assertEqual(args[0], "123:OLDBOT")
        self.assertEqual(args[1], "https://denta.tw1.ru/notifications/tg-webhook/tg-backfill-clinic/")
        self.assertEqual(kwargs.get("secret_token"), cs.telegram_webhook_secret)

    @patch("apps.notifications.telegram.tg_set_webhook")
    @patch("apps.notifications.telegram.tg_get_webhook_info")
    def test_skips_clinic_without_registered_webhook_url(self, mock_info, mock_set_webhook):
        cs = ClinicSettings.objects.create(
            clinic=self.clinic, name=self.clinic.name,
            telegram_bot_token="123:OLDBOT", telegram_webhook_secret="",
        )
        mock_info.return_value = {"ok": True, "result": {"url": ""}}

        self._run()

        cs.refresh_from_db()
        self.assertEqual(cs.telegram_webhook_secret, "")
        mock_set_webhook.assert_not_called()

    @patch("apps.notifications.telegram.tg_set_webhook")
    @patch("apps.notifications.telegram.tg_get_webhook_info")
    def test_skips_clinic_that_already_has_a_secret(self, mock_info, mock_set_webhook):
        ClinicSettings.objects.create(
            clinic=self.clinic, name=self.clinic.name,
            telegram_bot_token="123:OLDBOT", telegram_webhook_secret="already-set",
        )
        self._run()
        mock_info.assert_not_called()
        mock_set_webhook.assert_not_called()

    @patch("apps.notifications.telegram.tg_set_webhook")
    @patch("apps.notifications.telegram.tg_get_webhook_info")
    def test_skips_clinic_without_token(self, mock_info, mock_set_webhook):
        ClinicSettings.objects.create(clinic=self.clinic, name=self.clinic.name)
        self._run()
        mock_info.assert_not_called()


class WaWebhookDocumentBlocklistTestCase(TestCase):
    """Инцидент 2026-09-18: 691 файл .apk по 50-68MB, полученный через
    documentMessage в wa_webhook, забил диск сервера на 100% и трижды за
    сутки уронил сайт (PostgreSQL уходил в recovery mode). documentMessage
    скачивал и хранил ЛЮБОЙ файл без разбора типа/размера. Теперь
    исполняемые/установочные файлы не скачиваются вовсе, а прочие
    документы ограничены по размеру (WA_MEDIA_MAX_BYTES)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника WA", slug="wa-clinic")
        Branch.objects.create(name="Гл. филиал", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.client = Client()
        self.url = "/notifications/wa-webhook/"

    def _post(self, file_message_data):
        payload = {
            "typeWebhook": "incomingMessageReceived",
            "senderData": {"chatId": "996700000000@c.us", "sender": "996700000000@c.us"},
            "messageData": {
                "typeMessage": "documentMessage",
                "fileMessageData": file_message_data,
            },
        }
        import json
        return self.client.post(self.url, data=json.dumps(payload), content_type="application/json")

    @patch("apps.notifications.whatsapp.wa_download_media")
    def test_apk_by_filename_is_not_downloaded(self, mock_download):
        resp = self._post({"downloadUrl": "https://example.com/f.apk", "fileName": "update.apk"})
        self.assertEqual(resp.status_code, 200)
        mock_download.assert_not_called()
        from apps.notifications.models import WaMessage
        m = WaMessage.objects.get()
        self.assertFalse(m.media_file)
        self.assertIn("не сохраняем", m.body)

    @patch("apps.notifications.whatsapp.wa_download_media")
    def test_apk_by_mimetype_is_not_downloaded(self, mock_download):
        resp = self._post({
            "downloadUrl": "https://example.com/attachment",
            "mimeType": "application/vnd.android.package-archive",
        })
        self.assertEqual(resp.status_code, 200)
        mock_download.assert_not_called()

    @patch("apps.notifications.whatsapp.wa_download_media")
    def test_apk_visible_only_in_downloadurl_is_not_downloaded(self, mock_download):
        """Регрессия 2026-09-19: старая проверка брала ПЕРВОЕ непустое поле
        (fileName ИЛИ caption ИЛИ downloadUrl), поэтому непустой, но
        "чистый" fileName маскировал .apk, видимый только в downloadUrl —
        346 файлов (7.1GB) прошли блок-лист за сутки этим путём."""
        resp = self._post({
            "downloadUrl": "https://media.greenapi.com/waInstance/abc123.apk",
            "fileName": "IMG-20260919-WA0007",
        })
        self.assertEqual(resp.status_code, 200)
        mock_download.assert_not_called()

    @patch("apps.notifications.whatsapp.wa_download_media")
    def test_exe_is_not_downloaded(self, mock_download):
        resp = self._post({"downloadUrl": "https://example.com/f.exe", "fileName": "setup.exe"})
        self.assertEqual(resp.status_code, 200)
        mock_download.assert_not_called()

    @patch("apps.notifications.whatsapp.wa_download_media")
    def test_normal_pdf_is_still_downloaded(self, mock_download):
        mock_download.return_value = (b"%PDF-1.4 ...", "document.pdf")
        resp = self._post({"downloadUrl": "https://example.com/f.pdf", "fileName": "snimok.pdf"})
        self.assertEqual(resp.status_code, 200)
        mock_download.assert_called_once()
        from apps.notifications.models import WaMessage
        m = WaMessage.objects.get()
        self.assertTrue(m.media_file)


class TgGroupIgnoredTestCase(TestCase):
    """Расследование 2026-09-19: .apk-спам в chat_media шёл не из WhatsApp, а
    из Telegram-каналов (гэмблинг-реклама 1xBet/MelBet/Dbbet), в которых
    состоит номер, подключённый через telegram_ga.py (личный аккаунт
    Green-API). wa_webhook различал только WhatsApp-группы (chatId вида
    "...@g.us") — Telegram-группы/каналы (chatId вида "-100xxxxxxxxxx", без
    "@") под эту проверку не попадали и обрабатывались как обычная переписка
    с пациентом. Теперь для channel=tg отрицательный chatId полностью
    игнорируется — ни скачивания, ни записи в WaMessage."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника TG", slug="tg-clinic")
        Branch.objects.create(name="Гл. филиал", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.client = Client()
        self.url = "/notifications/wa-webhook/?ch=tg"

    @patch("apps.notifications.whatsapp.wa_download_media")
    def test_tg_group_message_with_document_is_ignored(self, mock_download):
        import json
        payload = {
            "typeWebhook": "incomingMessageReceived",
            "senderData": {"chatId": "-1003036908438", "sender": "-1003036908438", "chatName": "Spam channel"},
            "messageData": {
                "typeMessage": "documentMessage",
                "fileMessageData": {
                    "downloadUrl": "https://example.com/1xbet.apk",
                    "fileName": "1xBet.apk",
                },
            },
        }
        resp = self.client.post(self.url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        mock_download.assert_not_called()
        from apps.notifications.models import WaMessage
        self.assertEqual(WaMessage.objects.count(), 0)

    def test_tg_private_chat_is_still_processed(self):
        import json
        payload = {
            "typeWebhook": "incomingMessageReceived",
            "senderData": {"chatId": "10000000", "sender": "10000000"},
            "messageData": {
                "typeMessage": "textMessage",
                "textMessageData": {"textMessage": "Здравствуйте, можно записаться?"},
            },
        }
        resp = self.client.post(self.url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        from apps.notifications.models import WaMessage
        m = WaMessage.objects.get()
        self.assertEqual(m.channel, "tg")
        self.assertEqual(m.body, "Здравствуйте, можно записаться?")


class WaDownloadMediaSizeLimitTestCase(TestCase):
    """wa_download_media обрывает скачивание вложений больше WA_MEDIA_MAX_BYTES
    — защита от повторения инцидента 2026-09-18, даже для типов файлов вне
    блок-листа расширений (не только .apk)."""

    @patch("apps.notifications.whatsapp.urllib.request.urlopen")
    def test_oversized_file_is_rejected(self, mock_urlopen):
        from apps.notifications.whatsapp import wa_download_media

        class _Resp:
            def read(self, n):
                return b"x" * n  # отдаёт ровно сколько просят — имитирует поток

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        mock_urlopen.return_value = _Resp()
        data, name = wa_download_media("https://example.com/huge.jpg", max_bytes=100)
        self.assertIsNone(data)
        self.assertEqual(name, "")

    @patch("apps.notifications.whatsapp.urllib.request.urlopen")
    def test_normal_sized_file_is_accepted(self, mock_urlopen):
        from apps.notifications.whatsapp import wa_download_media

        class _Resp:
            def read(self, n):
                return b"small file content"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        mock_urlopen.return_value = _Resp()
        data, name = wa_download_media("https://example.com/small.jpg", max_bytes=1000)
        self.assertEqual(data, b"small file content")
        self.assertEqual(name, "small.jpg")


@override_settings(ROOT_URLCONF="config.urls")
class ServiceWorkerProductionRoutingTestCase(TestCase):
    """Регрессия: /sw.js и /manifest.json существовали только в
    config/urls_dev.py (локальная разработка) — manage.py test по
    умолчанию тоже грузит config.settings.development (ROOT_URLCONF =
    config.urls_dev), поэтому ни один тест их не проверял. В проде
    (config.settings.server) ROOT_URLCONF наследуется от base.py =
    config.urls, где этих маршрутов не было вовсе —
    navigator.serviceWorker.register('/sw.js') получал 404, и Web Push
    (фоновые уведомления вне открытой вкладки) не работал никогда.
    Здесь ЯВНО переключаемся на ПРОДАКШН urlconf (config.urls), чтобы
    тест бил именно по тому файлу, где баг реально был."""

    def test_service_worker_served_from_root(self):
        resp = self.client.get("/sw.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("javascript", resp["Content-Type"])
        self.assertIn(b"self.addEventListener('push'", resp.content)

    def test_manifest_served_from_root(self):
        resp = self.client.get("/manifest.json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["start_url"], "/")


class TgStaffBotTestCase(TestCase):
    """Меню сотрудника в боте клиники: привязка врача по своему контакту,
    приёмы на сегодня/выбранную дату, напоминания пациентам, группы."""

    def setUp(self):
        import json
        from datetime import datetime, time, timedelta
        from django.utils import timezone
        from apps.patients.models import Patient
        from apps.appointments.models import Appointment
        from apps.tenancy import set_current_clinic
        self.json = json
        self.clinic = Clinic.objects.create(name="Клиника Staff", slug="tg-staff-clinic")
        set_current_clinic(self.clinic)
        self.branch = Branch.objects.create(name="Гл.", address="-", phone="0", is_main=True, clinic=self.clinic)
        ClinicSettings.objects.update_or_create(
            clinic=self.clinic, defaults={"name": self.clinic.name, "telegram_bot_token": "123:ABC"})
        doc_role, _ = Role.objects.get_or_create(name=Role.DOCTOR)
        admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        self.doctor = User.objects.create(login="st_doc", name="Доктор Один", phone="+996 700 111 222",
                                          role=doc_role, clinic=self.clinic)
        self.doctor2 = User.objects.create(login="st_doc2", name="Доктор Два", phone="0700333444",
                                           role=doc_role, clinic=self.clinic)
        self.admin = User.objects.create(login="st_adm", name="Админ", phone="+996700555666",
                                         role=admin_role, clinic=self.clinic)
        self.patient = Patient.objects.create(first_name="Иван", last_name="Пациентов",
                                              phone="+996555000111", clinic=self.clinic, telegram_chat_id=999)
        self.other = Patient.objects.create(first_name="Пётр", last_name="Чужой",
                                            phone="+996555000222", clinic=self.clinic)
        self.day = timezone.localdate() + timedelta(days=3)
        start = timezone.make_aware(datetime.combine(self.day, time(10, 0)))
        self.appt = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, branch=self.branch, start_at=start,
            end_at=start + timedelta(minutes=30), clinic=self.clinic)
        Appointment.objects.create(
            patient=self.other, doctor=self.doctor2, branch=self.branch, start_at=start,
            end_at=start + timedelta(minutes=30), clinic=self.clinic)
        self.calls = []

    def tearDown(self):
        from apps.tenancy import clear_current_clinic
        clear_current_clinic()

    def _fake_call(self, method, payload, token=None):
        self.calls.append((method, payload))
        return {"ok": True, "result": {"message_id": 1}}

    def _update(self, update):
        from apps.notifications.views import _tg_handle_update
        with patch("apps.notifications.telegram._call", side_effect=self._fake_call):
            _tg_handle_update(self.json.dumps(update).encode(), self.clinic.slug)

    def _texts(self):
        return "\n".join(p.get("text", "") for _m, p in self.calls)

    def _link(self, user, tg_id):
        user.telegram_id = tg_id
        user.save(update_fields=["telegram_id"])

    def test_doctor_links_by_own_contact(self):
        self._update({"message": {"chat": {"id": 42, "type": "private"}, "from": {"id": 42},
                                  "contact": {"phone_number": "996700111222", "user_id": 42}}})
        self.doctor.refresh_from_db()
        self.assertEqual(self.doctor.telegram_id, 42)
        self.assertIn("подключены как врач", self._texts())
        from apps.notifications.models import WaMessage
        self.assertFalse(WaMessage.objects.exists())

    def test_foreign_contact_does_not_link_staff(self):
        self._update({"message": {"chat": {"id": 43, "type": "private"}, "from": {"id": 43},
                                  "contact": {"phone_number": "996700111222", "user_id": 77}}})
        self.doctor.refresh_from_db()
        self.assertIsNone(self.doctor.telegram_id)

    def test_doctor_sees_only_own_appointments_for_typed_date(self):
        self._link(self.doctor, 42)
        self._update({"message": {"chat": {"id": 42, "type": "private"}, "from": {"id": 42},
                                  "text": self.day.strftime("%d.%m")}})
        txt = self._texts()
        self.assertIn("Пациентов", txt)
        self.assertNotIn("Чужой", txt)

    def test_admin_sees_all_via_date_picker_callback(self):
        self._link(self.admin, 50)
        self._update({"callback_query": {"id": "q", "from": {"id": 50}, "data": "sdd:l:%s" % self.day.isoformat(),
                                         "message": {"chat": {"id": 50}, "message_id": 7}}})
        txt = self._texts()
        self.assertIn("Пациентов", txt)
        self.assertIn("Чужой", txt)
        self.assertIn("Доктор Два", txt)

    def test_picker_callback_rejected_for_non_staff(self):
        self._update({"callback_query": {"id": "q", "from": {"id": 999}, "data": "sdd:l:%s" % self.day.isoformat(),
                                         "message": {"chat": {"id": 999}, "message_id": 7}}})
        self.assertNotIn("Пациентов", self._texts())

    def test_date_picker_button(self):
        from apps.notifications.tg_staff import BTN_PICK_DATE
        self._link(self.doctor, 42)
        self._update({"message": {"chat": {"id": 42, "type": "private"}, "from": {"id": 42}, "text": BTN_PICK_DATE}})
        kb = self.calls[-1][1]["reply_markup"]["inline_keyboard"]
        self.assertTrue(kb[0][0]["callback_data"].startswith("sdd:l:"))

    def test_remind_sends_to_own_patients(self):
        self._link(self.doctor, 42)
        self._update({"callback_query": {"id": "q", "from": {"id": 42}, "data": "sdr:%s" % self.day.isoformat(),
                                         "message": {"chat": {"id": 42}, "message_id": 7}}})
        sent_to = [p.get("chat_id") for m, p in self.calls if m == "sendMessage"]
        self.assertEqual(sent_to, [999])
        self.assertIn("отправлены: <b>1</b> из 1", self._texts())

    def test_group_connect_by_admin_only(self):
        from apps.notifications.models import TgGroup
        grp = {"id": -100500, "type": "supergroup", "title": "Персонал"}
        self._link(self.doctor, 42)
        self._update({"message": {"chat": grp, "from": {"id": 42}, "text": "/group@clinic_bot"}})
        self.assertFalse(TgGroup.all_clinics.exists())
        self._link(self.admin, 50)
        self._update({"message": {"chat": grp, "from": {"id": 50}, "text": "/group@clinic_bot"}})
        g = TgGroup.all_clinics.get()
        self.assertEqual((g.chat_id, g.clinic_id, g.title), (-100500, self.clinic.pk, "Персонал"))
        # обычные сообщения группы не попадают в переписки CRM
        self._update({"message": {"chat": grp, "from": {"id": 1}, "text": "привет"}})
        from apps.notifications.models import WaMessage
        self.assertFalse(WaMessage.objects.exists())

    def test_group_notify_and_evening_summary(self):
        from datetime import datetime, time, timedelta
        from django.utils import timezone
        from apps.notifications.models import TgGroup
        from apps.notifications.whatsapp import notify_groups
        from apps.notifications.tg_staff import send_group_summaries
        TgGroup.all_clinics.create(clinic=self.clinic, chat_id=-1001, title="G")
        with patch("apps.notifications.telegram._call", side_effect=self._fake_call):
            notify_groups("🆕 *Новая запись* <x>", clinic=self.clinic)
        self.assertEqual(self.calls[-1][1]["chat_id"], -1001)
        self.assertIn("<b>Новая запись</b> &lt;x&gt;", self.calls[-1][1]["text"])
        self.calls.clear()
        evening = timezone.make_aware(datetime.combine(self.day - timedelta(days=1), time(19, 30)))
        with patch("apps.notifications.telegram._call", side_effect=self._fake_call):
            self.assertEqual(send_group_summaries(self.clinic, now=evening), 1)
            self.assertEqual(send_group_summaries(self.clinic, now=evening), 0)  # раз в день
        self.assertIn("Пациентов", self._texts())
        self.assertIn("Чужой", self._texts())

    def test_kicked_group_is_removed(self):
        from apps.notifications.models import TgGroup
        from apps.notifications.whatsapp import notify_groups
        TgGroup.all_clinics.create(clinic=self.clinic, chat_id=-1002)
        with patch("apps.notifications.telegram._call",
                   return_value={"ok": False, "error": b'{"description":"Forbidden: bot was kicked"}'}):
            notify_groups("x", clinic=self.clinic)
        self.assertFalse(TgGroup.all_clinics.exists())

    def test_new_appointment_notifies_doctor_in_telegram(self):
        from apps.appointments.views import notify_appointment_created
        self._link(self.doctor, 42)
        with patch("apps.notifications.telegram._call", side_effect=self._fake_call):
            notify_appointment_created(self.appt, created_by=self.admin)
        self.assertIn(42, [p.get("chat_id") for m, p in self.calls])

    def test_parse_date(self):
        from datetime import date
        from apps.notifications.tg_staff import parse_date
        self.assertEqual(parse_date("25.09.2026"), date(2026, 9, 25))
        self.assertEqual(parse_date("2026-09-25"), date(2026, 9, 25))
        self.assertEqual(parse_date("25/09/26"), date(2026, 9, 25))
        self.assertIsNone(parse_date("99.99"))
        self.assertIsNone(parse_date("привет"))
