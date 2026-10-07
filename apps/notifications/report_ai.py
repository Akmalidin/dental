"""ИИ в «Отчётах»: сжатая сводка реальных цифр клиники (для чата-помощника и
для рекомендаций) и «Рекомендации ИИ на сегодня» — раз в день на клинику и
филиал, по реальным данным (раньше блок был заглушкой с выдуманными цифрами)."""
import json
import logging

from django.core.cache import cache
from django.utils import timezone

from . import assistant as core

log = logging.getLogger("apps")

# куда ведёт кнопка рекомендации
ACTIONS = {
    "schedule": "/new/schedule/", "debtors": "debtors", "doctors": "doctors", "cancelled": "cancelled",
    "funnel": "/new/funnel/", "messages": "/new/messages/", "cashdesk": "/new/cashdesk/",
    "repeat": "repeat", "expenses": "expenses", "sources": "sources",
}


def report_summary(branch_id=None):
    """Месяц до сегодняшнего дня — те же данные, что на странице «Отчёты»."""
    from apps.users.views import _newui_reports_data
    d = _newui_reports_data(branch_id)
    today = timezone.localdate()
    inactive = [r for r in d["repeatVisits"] if (r.get("daysSince") or 0) > 180]
    return {
        "period": "с %s по %s" % (today.replace(day=1).strftime("%d.%m.%Y"), today.strftime("%d.%m.%Y")),
        "paid_month": round(d["revenueMonth"]),
        "billed_month": round(d.get("billedMonth") or 0),
        "visits_completed": d["completed"], "visits_cancelled": d["cancelled"],
        "cancelled_pct": d["cancelledPct"], "no_show": d["noshow"],
        "expenses_month": round(d["expensesTotal"]),
        "expenses_by_category": d["expensesByCategory"][:6],
        "debt_total": round(-d["debtorsTotal"]), "debtors_count": len(d["debtorsList"]),
        "top_debtors": [{"name": x["name"], "debt": round(-x["balance"])} for x in d["debtorsList"][:5]],
        "doctors": [{"doctor": x["doctor"], "visits": x["count"], "billed": round(x.get("billed", 0)),
                     "paid": round(x["revenue"]), "avg_check": round(x["avgCheck"]),
                     "fill_rate_pct": x["fillRatePct"]} for x in d["doctorStats"]],
        "paid_by_week": d["weeklyRevenue"],
        "cancel_reasons": d["cancelReasons"][:6],
        "lead_sources": d["leadSources"][:6],
        "patients_not_seen_6_months": len(inactive),
        "branches": [{"branch": b["branch"], "paid": round(b["revenue"]), "billed": round(b.get("billed", 0)),
                      "completed": b["completed"], "cancelled": b["cancelled"], "debt": round(b["debt"])}
                     for b in d["branchStats"]],
    }


def can_see(user):
    return user.can_access("finance") and (user.is_admin or user.is_superadmin)


def insights(request, branch_id=None, refresh=False):
    """[{type, icon, title, text, action}] на сегодня (кэш до конца суток)."""
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic()
    key = "report_ai:%s:%s:%s" % (clinic.pk if clinic else 0, branch_id or 0, timezone.localdate().isoformat())
    cached = None if refresh else cache.get(key)
    if cached:
        return cached, None
    summary = report_summary(branch_id)
    cur = ""
    try:
        from apps.settings_clinic.models import ClinicSettings
        cur = ClinicSettings.get().currency_label
    except Exception:  # noqa: BLE001
        pass
    prompt = (
        "Ты — аналитик стоматологической клиники. По реальным цифрам ниже дай 4–6 коротких полезных "
        "рекомендаций руководителю на сегодня. Только на основе этих данных, ничего не выдумывай; если "
        "данных мало — так и скажи одной рекомендацией. Суммы — в валюте «%s», числом. Пиши по-русски.\n"
        "«paid» — реально получено денег, «billed» — оказано услуг (счета за вычетом скидок).\n"
        "Ответь ТОЛЬКО JSON: {\"insights\": [{\"type\": \"warn\"|\"good\", \"icon\": один эмодзи, "
        "\"title\": до 70 символов, \"text\": 1–2 предложения, \"action\": одно из %s}]}\n\nДанные: %s"
    ) % (cur, ", ".join(ACTIONS), json.dumps(summary, ensure_ascii=False, default=str))
    data, err = core._chat([{"role": "user", "content": prompt}], tools=False)
    if err:
        return None, "ИИ временно недоступен"
    text = (data["choices"][0]["message"].get("content") or "").strip()
    try:
        raw = json.loads(text[text.index("{"):text.rindex("}") + 1])["insights"]
    except Exception:  # noqa: BLE001
        log.warning("report_ai: не удалось разобрать ответ: %s", text[:300])
        return None, "ИИ вернул непонятный ответ"
    out = []
    for i in raw[:6]:
        act = i.get("action") if i.get("action") in ACTIONS else ""
        out.append({"type": "good" if i.get("type") == "good" else "warn", "icon": (i.get("icon") or "•")[:4],
                    "title": str(i.get("title") or "")[:120], "text": str(i.get("text") or "")[:400],
                    "action": act, "target": ACTIONS.get(act, "")})
    result = {"items": out, "updated": timezone.localtime().strftime("%d.%m.%Y %H:%M")}
    cache.set(key, result, 60 * 60 * 24)
    return result, None
