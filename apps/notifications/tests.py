from unittest.mock import patch

from django.test import TestCase, Client

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
        mock_set_webhook.assert_not_called()
