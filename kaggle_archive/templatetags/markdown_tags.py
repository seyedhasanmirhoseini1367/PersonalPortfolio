import markdown as md
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter(name='render_markdown', is_safe=True)
def render_markdown(value):
    if not value:
        return ''
    return mark_safe(md.markdown(str(value), extensions=['fenced_code', 'tables']))
