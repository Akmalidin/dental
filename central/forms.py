from django import forms
from apps.tenants.models import Tenant, Subscription
from django.utils.text import slugify
from datetime import date


class TenantCreateForm(forms.Form):
    name = forms.CharField(label="Название клиники", max_length=200)
    slug = forms.SlugField(label="Поддомен (например: clinic1)")
    owner_email = forms.EmailField(label="Email владельца")
    phone = forms.CharField(label="Телефон", max_length=30, required=False)
    plan = forms.ChoiceField(
        label="Тарифный план",
        choices=Subscription.PLAN_CHOICES if hasattr(Subscription, "PLAN_CHOICES") else [
            ("trial", "Пробный"), ("basic", "Базовый"), ("pro", "Pro"), ("enterprise", "Enterprise")
        ],
        initial="trial",
    )

    def clean_slug(self):
        slug = self.cleaned_data["slug"]
        if Tenant.objects.filter(schema_name=slug).exists():
            raise forms.ValidationError("Такой поддомен уже существует")
        return slug

    def save(self):
        data = self.cleaned_data
        tenant = Tenant(
            schema_name=data["slug"],
            name=data["name"],
            slug=data["slug"],
            owner_email=data["owner_email"],
            phone=data.get("phone", ""),
        )
        tenant.save()

        from apps.tenants.models import Domain
        Domain.objects.create(
            domain=f"{data['slug']}.akmsoft.kg",
            tenant=tenant,
            is_primary=True,
        )

        Subscription.objects.create(
            tenant=tenant,
            plan=data["plan"],
            started_at=date.today(),
            is_active=True,
        )
        return tenant
