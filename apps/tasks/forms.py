from django import forms
from .models import Task


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["title", "description", "assigned_to", "due_date", "status", "priority"]
        widgets = {
            "due_date": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "assigned_to": forms.CheckboxSelectMultiple(),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["due_date"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["status"].required = False      # по умолчанию «Ожидает»
        self.fields["assigned_to"].required = False
        # Создателя (себя) не показываем в списке исполнителей
        if user is not None and getattr(user, "pk", None):
            self.fields["assigned_to"].queryset = (
                self.fields["assigned_to"].queryset.exclude(pk=user.pk))
