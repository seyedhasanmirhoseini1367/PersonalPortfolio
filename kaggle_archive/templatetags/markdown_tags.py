import markdown as md
from django import template
from django.utils.safestring import mark_safe

from stories.sanitize import clean_html

register = template.Library()


@register.filter(name='render_markdown', is_safe=True)
def render_markdown(value):
    """Markdown -> HTML, cleaned. The text comes from third parties (Kaggle
    write-ups), and Markdown allows raw HTML, so scripts and event handlers
    are stripped before it is marked safe."""
    if not value:
        return ''
    return mark_safe(clean_html(md.markdown(str(value), extensions=['fenced_code', 'tables'])))
