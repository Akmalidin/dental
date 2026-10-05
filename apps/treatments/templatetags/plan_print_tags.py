from django import template

register = template.Library()


@register.filter
def money(v):
    """12345.6 → «12 346» (пробел-разделитель тысяч, без копеек)."""
    try:
        return "{:,.0f}".format(float(v or 0)).replace(",", " ")
    except (TypeError, ValueError):
        return v
