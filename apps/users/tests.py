from django.test import TestCase
from apps.users.models import User
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
