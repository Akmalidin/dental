from django.test import TestCase
from apps.users.models import User, Permission, PermissionCategory, Role, Clinic
from apps.users.forms import UserForm


class UserColorFieldTestCase(TestCase):
    def test_color_optional_and_blank_by_default(self):
        u = User.objects.create(login="staff_nocolor", name="Без цвета", email="nc@test.local")
        self.assertEqual(u.color, "")

    def test_color_can_be_set(self):
        u = User.objects.create(login="staff_color", name="С цветом", email="c@test.local", color="#F59E0B")
        self.assertEqual(u.color, "#F59E0B")

    def test_form_does_not_require_color(self):
        form = UserForm(data={
            "login": "staff_form", "name": "Форма", "email": "form@test.local",
            "password": "", "full_access": "on",
        })
        form.is_valid()
        self.assertNotIn("color", form.errors)


class PermissionCatalogTestCase(TestCase):
    def test_permission_has_category_and_code(self):
        # test.dummy_action — заведомо не пересекается с реальным каталогом
        # прав (сидится data migration'ом Task 2, code там уникален)
        p = Permission.objects.create(
            code="test.dummy_action", category=PermissionCategory.FINANCE,
            label="Приём оплат",
        )
        self.assertEqual(p.category, "finance")
        self.assertEqual(str(p), "Приём оплат")


class RoleClinicScopingTestCase(TestCase):
    def setUp(self):
        self.clinic_a = Clinic.objects.create(name="Клиника A", slug="clinic-a-roles")
        self.clinic_b = Clinic.objects.create(name="Клиника B", slug="clinic-b-roles")

    def test_system_role_has_no_clinic(self):
        role = Role.objects.create(name="doctor_test1", is_system=True)
        self.assertIsNone(role.clinic)

    def test_custom_role_scoped_to_one_clinic(self):
        role = Role.objects.create(name="Кассир", clinic=self.clinic_a)
        self.assertEqual(role.clinic, self.clinic_a)

    def test_same_role_name_allowed_in_different_clinics(self):
        Role.objects.create(name="Кассир", clinic=self.clinic_a)
        # не должно упасть — имя уникально ТОЛЬКО в пределах клиники, не глобально
        role_b = Role.objects.create(name="Кассир", clinic=self.clinic_b)
        self.assertEqual(role_b.clinic, self.clinic_b)


class RoleHasPermTestCase(TestCase):
    def test_has_perm_true_when_granted(self):
        perm = Permission.objects.create(code="test.dummy_action2", category="finance", label="X")
        role = Role.objects.create(name="custom_cashier_test", is_system=True)
        role.granular_permissions.add(perm)
        self.assertTrue(role.has_perm("test.dummy_action2"))

    def test_has_perm_false_when_not_granted(self):
        role = Role.objects.create(name="custom_empty_test", is_system=True)
        self.assertFalse(role.has_perm("finance.accept_payments"))


class PermissionSeedTestCase(TestCase):
    def test_catalog_seeded_with_nine_permissions(self):
        self.assertEqual(Permission.objects.count(), 9)

    def test_system_roles_marked_is_system(self):
        for name in ["superadmin", "admin_main", "admin", "doctor", "nurse"]:
            role = Role.objects.get(name=name, clinic__isnull=True)
            self.assertTrue(role.is_system)

    def test_admin_role_has_no_staff_manage_by_default(self):
        role = Role.objects.get(name="admin", clinic__isnull=True)
        self.assertFalse(role.has_perm("staff.manage"))

    def test_admin_main_has_staff_manage_by_default(self):
        role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.assertTrue(role.has_perm("staff.manage"))
