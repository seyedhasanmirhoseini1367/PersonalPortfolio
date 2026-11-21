from django import template
from django.utils.safestring import mark_safe

from stories.sanitize import clean_html

register = template.Library()


@register.filter
def clean_story_html(value):
    """Sanitised story HTML, safe to render (see stories/sanitize.py)."""
    return mark_safe(clean_html(value))
