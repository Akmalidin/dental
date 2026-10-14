"""Смена статуса заказа технику и уведомления — общие для страницы клиники
(views.order_status) и кабинета техника (my_views)."""
from datetime import timedelta

from django.utils import timezone

from .models import TechnicianOrderEvent, TechnicianTask

# Куда техник может перевести заказ сам (из какого статуса → в какие).
# «Примерка», «Установлено» и «Отменено» ставит клиника.
TECH_MOVES = {
    TechnicianTask.STATUS_TRANSFERRED: (TechnicianTask.STATUS_IN_PROGRESS,),
    TechnicianTask.STATUS_IN_PROGRESS: (TechnicianTask.STATUS_READY,),
    TechnicianTask.STATUS_CORRECTION: (TechnicianTask.STATUS_IN_PROGRESS, TechnicianTask.STATUS_READY),
}


def order_title(task):
    p = task.patient
    who = f"{p.last_name} {p.first_name}".strip() if p else ""
    svc = task.service.name if task.service_id else "работа"
    return f"{svc}{' — ' + who if who else ''}{' (зуб ' + task.tooth_number + ')' if task.tooth_number else ''}"


def apply_status(task, new_status, user):
    """Сменить статус: ключевые даты, гарантия, запись в процедуру, журнал,
    уведомления. new_status уже проверен вызывающим."""
    old = task.status
    task.status = new_status
    today = timezone.localdate()
    if new_status == TechnicianTask.STATUS_READY and not task.ready_at:
        task.ready_at = today
    if new_status == TechnicianTask.STATUS_INSTALLED:
        if not task.installed_at:
            task.installed_at = today
        task.warranty_until = task.compute_warranty()
        if task.cure_id:
            from apps.treatments.models import TreatmentCure
            TreatmentCure.objects.filter(pk=task.cure_id).update(
                technician=task.technician, warranty_until=task.warranty_until, lab_order=task)
    task.save()
    TechnicianOrderEvent.objects.create(task=task, status=new_status, by=user)
    if old != new_status:
        notify_status(task, new_status, user)


def _send(user, title, body, link, actor=None):
    if user is None or not user.is_active:
        return
    from apps.notifications.models import Notification
    try:
        Notification.send(user, title, body, type="task", link=link, actor=actor, clinic=user.clinic)
    except Exception:  # noqa: BLE001 — уведомление не должно ломать смену статуса
        pass


def _clinic_staff(task):
    """Кому в клинике сообщать о работе: врач приёма и администраторы."""
    from apps.users.models import Role, User
    from django.db.models import Q
    users = {}
    doctor = getattr(task.treatment, "doctor", None) if task.treatment_id else None
    if doctor is not None:
        users[doctor.pk] = doctor
    admins = (User.objects.filter(clinic_id=task.clinic_id, is_active=True)
              .filter(Q(role__name__in=[Role.ADMIN, Role.ADMIN_MAIN]) | Q(roles__name__in=[Role.ADMIN, Role.ADMIN_MAIN]))
              .distinct())
    for u in admins:
        users[u.pk] = u
    return users.values()


def notify_status(task, new_status, by):
    tech_user = task.technician.user if task.technician_id else None
    by_tech = by is not None and tech_user is not None and by.pk == tech_user.pk
    if by_tech and new_status == TechnicianTask.STATUS_READY:
        for u in _clinic_staff(task):
            _send(u, f"Работа готова: {order_title(task)}", f"Техник {task.technician.name} отметил заказ готовым.",
                  "/new/lab/", actor=by)
    elif not by_tech and new_status == TechnicianTask.STATUS_CORRECTION:
        clinic = task.technician.clinic.name if task.technician.clinic_id else ""
        _send(tech_user, f"Коррекция: {order_title(task)}",
              f"{'Клиника: ' + clinic + '. ' if clinic else ''}{task.doctor_comment[:300]}", "/new/lab/my/", actor=by)


def notify_new_order(task):
    tech_user = task.technician.user if task.technician_id else None
    if tech_user is None:
        return
    due = task.expected_ready.strftime("%d.%m.%Y") if task.expected_ready else "не указан"
    clinic = task.technician.clinic.name if task.technician.clinic_id else ""
    _send(tech_user, f"Новый заказ: {order_title(task)}",
          f"{'Клиника: ' + clinic + '. ' if clinic else ''}Срок: {due}. {task.doctor_comment[:250]}".strip(),
          "/new/lab/my/")


# ─── Переписка по заказу и перенос срока ─────────────────────────────────────

def _fmt(d):
    return d.strftime("%d.%m.%Y") if d else "—"


def messages_json(task):
    from .models import TechnicianOrderMessage as M
    out = []
    for m in task.messages.all():
        out.append({
            "id": m.pk, "kind": m.kind, "fromTech": m.from_technician,
            "author": (m.author.name if m.author_id else "") or ("Техник" if m.from_technician else "Клиника"),
            "text": m.text, "at": timezone.localtime(m.created_at).strftime("%d.%m %H:%M"),
            "oldDate": _fmt(m.old_date) if m.kind == M.KIND_DEADLINE else "",
            "proposed": _fmt(m.proposed_date) if m.kind == M.KIND_DEADLINE else "",
            "decision": m.decision, "decisionLabel": m.get_decision_display() if m.decision else "",
            "decidedBy": m.decided_by.name if m.decided_by_id else "",
        })
    return out


def pending_deadline(task):
    from .models import TechnicianOrderMessage as M
    return task.messages.filter(kind=M.KIND_DEADLINE, decision=M.PENDING).first()


def add_comment(task, user, text, from_tech):
    from .models import TechnicianOrderMessage as M
    m = M.objects.create(task=task, author=user, from_technician=from_tech, text=text)
    if from_tech:
        for u in _clinic_staff(task):
            _send(u, f"Техник пишет: {order_title(task)}", text[:300], f"/new/lab/?order={task.pk}", actor=user)
    else:
        tech_user = task.technician.user if task.technician_id else None
        clinic = task.technician.clinic.name if task.technician.clinic_id else ""
        _send(tech_user, f"Клиника пишет: {order_title(task)}",
              f"{clinic + ': ' if clinic else ''}{text[:300]}", "/new/lab/my/", actor=user)
    return m


def request_deadline(task, user, new_date, reason):
    """Техник просит новый срок. Ошибка — строкой, иначе None."""
    from .models import TechnicianOrderMessage as M
    today = timezone.localdate()
    if task.status not in TechnicianTask.OPEN_STATUSES:
        return "Срок можно перенести только у заказа в работе"
    if new_date is None or new_date < today or new_date > today + timedelta(days=365):
        return "Укажите дату не раньше сегодняшней"
    if new_date == task.expected_ready:
        return "Это и есть текущий срок"
    if pending_deadline(task) is not None:
        return "Прошлый запрос ещё ждёт решения клиники"
    M.objects.create(task=task, author=user, from_technician=True, kind=M.KIND_DEADLINE, text=reason,
                     old_date=task.expected_ready, proposed_date=new_date, decision=M.PENDING)
    for u in _clinic_staff(task):
        _send(u, f"Техник просит перенести срок: {order_title(task)}",
              f"С {_fmt(task.expected_ready)} на {_fmt(new_date)}. {reason[:250]}".strip(),
              f"/new/lab/?order={task.pk}", actor=user)
    return None


def decide_deadline(msg, user, approve):
    from .models import TechnicianOrderMessage as M
    task = msg.task
    msg.decision = M.APPROVED if approve else M.DECLINED
    msg.decided_by, msg.decided_at = user, timezone.now()
    msg.save(update_fields=["decision", "decided_by", "decided_at"])
    if approve:
        task.expected_ready = msg.proposed_date
        task.save(update_fields=["expected_ready", "updated_at"])
    tech_user = task.technician.user if task.technician_id else None
    _send(tech_user,
          (f"Срок перенесён на {_fmt(msg.proposed_date)}" if approve else "Перенос срока отклонён")
          + f": {order_title(task)}",
          "" if approve else f"Срок остаётся {_fmt(task.expected_ready)}.", "/new/lab/my/", actor=user)
