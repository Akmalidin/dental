from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.assistant.models import Conversation


@login_required
def conversation(request):
    """Реплики активной беседы — панель подгружает их при открытии, поэтому
    история переживает переход между страницами."""
    conv = Conversation.active_for(request.user)
    return JsonResponse({
        "messages": [
            {"role": m.role, "text": m.text}
            for m in conv.recent(limit=50)
        ],
    })


@login_required
@require_POST
def conversation_clear(request):
    """Кнопка «Очистить»: закрываем текущую беседу, следующий вопрос начнёт
    новую. Реплики не удаляем — они остаются журналом."""
    conv = Conversation.active_for(request.user)
    conv.closed_at = timezone.now()
    conv.save(update_fields=["closed_at"])
    return JsonResponse({"ok": True})
