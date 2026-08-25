from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.db.models import Q
from django.views.decorators.http import require_POST

from .decorators import require_permission
from .models import Role, Permission, PermissionCategory


def roles_for_clinic(clinic):
    """Роли, видимые клинике: системные (общие для всех) + свои кастомные.

    Суперадмин AKM SOFT — служебная роль платформы, не относится к персоналу
    клиники и не должна быть видна/доступна для управления директору клиники.
    """
    return Role.objects.filter(Q(clinic__isnull=True) | Q(clinic=clinic)).exclude(name=Role.SUPERADMIN)


@login_required
@require_permission("staff.manage")
def role_list(request):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic()
    roles = roles_for_clinic(clinic).order_by("-is_system", "name")
    return render(request, "users/roles_list.html", {"roles": roles})


@login_required
@require_permission("staff.manage")
def role_create(request):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic()
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, _("Укажите название роли"))
            return redirect("role_list")
        if Role.objects.filter(clinic=clinic, name=name).exists():
            messages.error(request, _("Роль с таким названием уже есть в этой клинике"))
            return redirect("role_list")
        role = Role.objects.create(name=name, clinic=clinic, is_system=False)
        messages.success(request, _("Роль создана"))
        return redirect("role_edit", pk=role.pk)
    return redirect("role_list")


@login_required
@require_permission("staff.manage")
def role_edit(request, pk):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic()
    role = get_object_or_404(roles_for_clinic(clinic), pk=pk)
    categories = [(c.value, c.label, Permission.objects.filter(category=c.value)) for c in PermissionCategory]
    if request.method == "POST":
        if not role.is_system:
            new_name = (request.POST.get("name") or "").strip()
            if new_name:
                role.name = new_name
                role.save(update_fields=["name"])
        if role.is_system and not request.user.is_superadmin:
            # Системная роль («Директор», «Доктор» и т.д.) — ОДНА строка в
            # БД на всю платформу (clinic=None), не только для этой клиники.
            # Если разрешить менять её права любому директору с staff.manage —
            # правки применятся ко всем клиникам сразу. Кастомизация — только
            # через «Дублировать» (role_duplicate) в свою копию, назначаемую
            # персоналу так же, как системная (см. roleOptions в _shared_options).
            messages.error(request, _(
                "Права системной роли «%(name)s» может менять только супер-админ "
                "платформы — эта роль общая для всех клиник. Чтобы задать свои "
                "права, нажмите «Дублировать» и настройте копию."
            ) % {"name": role.display_name})
            return redirect("role_edit", pk=role.pk)
        codes = request.POST.getlist("permissions")
        role.granular_permissions.set(Permission.objects.filter(code__in=codes))
        messages.success(request, _("Права роли обновлены"))
        return redirect("role_list")
    granted = set(role.granular_permissions.values_list("code", flat=True))
    return render(request, "users/role_form.html", {
        "role": role, "categories": categories, "granted": granted,
    })


@login_required
@require_permission("staff.manage")
@require_POST
def role_duplicate(request, pk):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic()
    original = get_object_or_404(roles_for_clinic(clinic), pk=pk)
    base_name = f"{original.name} (копия)"
    name = base_name
    n = 1
    while Role.objects.filter(clinic=clinic, name=name).exists():
        n += 1
        name = f"{base_name} {n}"
    copy = Role.objects.create(name=name, clinic=clinic, is_system=False)
    copy.granular_permissions.set(original.granular_permissions.all())
    messages.success(request, _("Роль скопирована"))
    return redirect("role_edit", pk=copy.pk)


@login_required
@require_permission("staff.manage")
@require_POST
def role_delete(request, pk):
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic()
    role = get_object_or_404(roles_for_clinic(clinic), pk=pk)
    if role.is_system:
        messages.error(request, _("Системную роль удалить нельзя"))
        return redirect("role_list")
    if role.users.exists():
        messages.error(request, _("У роли есть сотрудники — сначала назначьте им другую роль"))
        return redirect("role_list")
    role.delete()
    messages.success(request, _("Роль удалена"))
    return redirect("role_list")
