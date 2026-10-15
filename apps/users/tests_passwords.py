import json

from django.test import Client, TestCase

from apps.tenancy import clear_current_clinic, set_current_clinic
from apps.users.models import Clinic, Role, User
from apps.users.passwords import SESSION_FLAG, is_weak, password_problems


class PasswordStrengthTestCase(TestCase):
    def test_weak_and_strong(self):
        for pw in ("1111", "123456", "12345678", "00000000", "qwerty", "password"):
            self.assertTrue(is_weak(pw), pw)
        self.assertEqual(password_problems("Zub-Klinika-77"), [])

    def test_similar_to_login(self):
        u = User(login="aibek.doctor", name="Айбек")
        self.assertTrue(is_weak("aibek.doctor", u))


class ForcedChangeAndProfileTestCase(TestCase):
    """Отчёт безопасности: слабый пароль → обязательная смена после входа (№9),
    смена в профиле только со старым паролем и без strip (№12)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Пароли", slug="pw-cl")
        set_current_clinic(self.clinic)
        role = lambda n: Role.objects.get(name=n, clinic__isnull=True)  # noqa: E731
        self.director = User.objects.create(login="pw_dir", name="Директор", role=role("admin_main"),
                                            clinic=self.clinic)
        self.director.set_password("Strong-Pass-91")
        self.director.save()
        self.doc = User.objects.create(login="pw_doc", name="Врач", role=role("doctor"), clinic=self.clinic)
        self.doc.set_password("1111")
        self.doc.save()
        clear_current_clinic()

    def test_weak_password_login_forces_change(self):
        c = Client()
        r = c.post("/login/", {"login": "pw_doc", "password": "1111"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/password-change/")
        self.assertTrue(c.session.get(SESSION_FLAG))
        # Остальное закрыто, пока пароль не сменён.
        r = c.get("/new/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/password-change/")
        r = c.post("/finance/payments/create/", {"amount": "1"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(c.get("/password-change/").status_code, 200)
        # Слабый новый пароль не принимается.
        r = c.post("/password-change/", {"old_password": "1111", "new_password": "22222222",
                                         "new_password2": "22222222"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(c.session.get(SESSION_FLAG))
        # Неверный текущий.
        r = c.post("/password-change/", {"old_password": "nope", "new_password": "Good-Pass-2026",
                                         "new_password2": "Good-Pass-2026"})
        self.assertEqual(r.status_code, 200)
        r = c.post("/password-change/", {"old_password": "1111", "new_password": "Good-Pass-2026",
                                         "new_password2": "Good-Pass-2026"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(c.session.get(SESSION_FLAG))
        self.doc.refresh_from_db()
        self.assertTrue(self.doc.check_password("Good-Pass-2026"))
        self.assertNotEqual(c.get("/new/").get("Location"), "/password-change/")

    def test_strong_password_login_not_forced(self):
        c = Client()
        r = c.post("/login/", {"login": "pw_dir", "password": "Strong-Pass-91"})
        self.assertEqual(r.status_code, 302)
        self.assertNotEqual(r["Location"], "/password-change/")
        self.assertFalse(c.session.get(SESSION_FLAG))

    def test_profile_requires_old_password_and_keeps_spaces(self):
        c = Client()
        c.force_login(self.director)
        base = {"name": "Директор", "login": "pw_dir"}
        c.post("/profile/", {**base, "password": "New-Strong-55", "password2": "New-Strong-55"})
        self.director.refresh_from_db()
        self.assertTrue(self.director.check_password("Strong-Pass-91"))
        c.post("/profile/", {**base, "old_password": "Strong-Pass-91",
                             "password": " New-Strong-55 ", "password2": " New-Strong-55 "})
        self.director.refresh_from_db()
        self.assertTrue(self.director.check_password(" New-Strong-55 "))
        # Сессия осталась живой (update_session_auth_hash).
        self.assertEqual(c.get("/profile/").status_code, 200)

    def test_email_login_with_duplicate_email_no_500(self):
        for u in (self.director, self.doc):
            u.email = "same@example.com"
            u.save(update_fields=["email"])
        r = Client().post("/login/", {"login": "same@example.com", "password": "Strong-Pass-91"})
        self.assertEqual(r.status_code, 200)


class StaffEscalationTestCase(TestCase):
    """Отчёт безопасности №7: staff.manage не даёт стать директором и править директора."""

    def setUp(self):
        from apps.users.models import Permission
        self.clinic = Clinic.objects.create(name="Роли", slug="esc-cl")
        set_current_clinic(self.clinic)
        role = lambda n: Role.objects.get(name=n, clinic__isnull=True)  # noqa: E731
        self.admin_main_role = role("admin_main")
        self.hr_role = Role.objects.create(name="HR", clinic=self.clinic, is_system=False)
        self.hr_role.granular_permissions.add(Permission.objects.get(code="staff.manage"))
        self.director = User.objects.create(login="esc_dir", name="Директор", role=self.admin_main_role,
                                            clinic=self.clinic)
        self.hr = User.objects.create(login="esc_hr", name="Кадры", role=self.hr_role, clinic=self.clinic)
        other = Clinic.objects.create(name="Чужая", slug="esc-other")
        self.foreign_role = Role.objects.create(name="Чужая роль", clinic=other, is_system=False)
        clear_current_clinic()

    def _form(self, u, **extra):
        data = {"login": u.login, "name": u.name, "is_active": "on", "color": "#000000",
                "role": u.role_id, "full_access": "on"}
        data.update(extra)
        return data

    def test_hr_cannot_become_director(self):
        c = Client()
        c.force_login(self.hr)
        c.post(f"/users/{self.hr.pk}/edit/", self._form(self.hr, role=self.admin_main_role.pk))
        self.hr.refresh_from_db()
        self.assertEqual(self.hr.role_id, self.hr_role.pk)
        self.assertFalse(self.hr.is_admin_main)

    def test_hr_cannot_edit_director(self):
        c = Client()
        c.force_login(self.hr)
        c.post(f"/users/{self.director.pk}/edit/", self._form(self.director, password="Hacked-Pass-1",
                                                              is_active=""))
        self.director.refresh_from_db()
        self.assertTrue(self.director.is_active)
        self.assertFalse(self.director.check_password("Hacked-Pass-1"))

    def test_foreign_roles_not_offered(self):
        from apps.users.forms import UserForm
        set_current_clinic(self.clinic)
        try:
            form = UserForm(actor=self.director)
            self.assertNotIn(self.foreign_role, form.fields["role"].queryset)
            self.assertIn(self.hr_role, form.fields["role"].queryset)
        finally:
            clear_current_clinic()


class ImpersonationReadOnlyTestCase(TestCase):
    """Отчёт безопасности №13: «Войти как» — только просмотр."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Вход как", slug="imp-cl")
        set_current_clinic(self.clinic)
        role = lambda n: Role.objects.get(name=n, clinic__isnull=True)  # noqa: E731
        self.director = User.objects.create(login="imp_dir", name="Директор", role=role("admin_main"),
                                            clinic=self.clinic)
        self.doc = User.objects.create(login="imp_doc", name="Врач", role=role("doctor"), clinic=self.clinic)
        clear_current_clinic()

    def test_post_blocked_while_impersonating(self):
        c = Client()
        c.force_login(self.director)
        s = c.session
        s["imp_as"] = self.doc.pk
        s.save()
        r = c.post("/profile/", {"name": "Взлом", "login": "imp_doc"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("Режим просмотра", json.loads(r.content)["error"])
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.name, "Врач")
        self.assertEqual(c.get("/new/").status_code in (200, 302), True)


class SyncExportSecretsTestCase(TestCase):
    """Отчёт безопасности №6: в выгрузке нет секретов, а через браузер — и хешей паролей."""

    def setUp(self):
        from apps.settings_clinic.models import ClinicSettings
        self.clinic = Clinic.objects.create(name="Синк", slug="sync-sec")
        set_current_clinic(self.clinic)
        role = lambda n: Role.objects.get(name=n, clinic__isnull=True)  # noqa: E731
        self.director = User.objects.create(login="sx_dir", name="Директор", role=role("admin_main"),
                                            clinic=self.clinic)
        self.director.set_password("Strong-Pass-91")
        self.director.save()
        self.admin = User.objects.create(login="sx_adm", name="Админ", role=role("admin"), clinic=self.clinic)
        cs, _ = ClinicSettings.objects.get_or_create(clinic=self.clinic, defaults={"name": "Синк"})
        cs.wa_token = "WA-SECRET"
        cs.telegram_bot_token = "TG-SECRET"
        cs.save()
        clear_current_clinic()

    def test_browser_export(self):
        c = Client()
        c.force_login(self.admin)
        self.assertEqual(c.get("/sync/export/").status_code, 403)
        c.force_login(self.director)
        r = c.get("/sync/export/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNotIn("WA-SECRET", body)
        self.assertNotIn("TG-SECRET", body)
        self.assertNotIn("pbkdf2", body)
        self.assertNotIn(self.director.password, body)

    def test_device_export_keeps_hashes_but_no_secrets(self):
        from apps.sync.core import export_clinic
        blocks = export_clinic(self.clinic)
        dump = json.dumps(blocks)
        self.assertIn(self.director.password, dump)
        self.assertNotIn("WA-SECRET", dump)
