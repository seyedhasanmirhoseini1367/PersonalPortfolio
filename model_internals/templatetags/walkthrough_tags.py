import re

import markdown as md
from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

# Block math ($$...$$) before inline math ($...$) so a $$ span is never
# mistaken for two adjacent inline spans.
_MATH_RE = re.compile(r'(\$\$.+?\$\$|\$[^\$\n]+?\$)', re.DOTALL)
_PLACEHOLDER_RE = re.compile(r'\x00MATH(\d+)\x00')


@register.filter(name='render_walkthrough_markdown', is_safe=True)
def render_walkthrough_markdown(value):
    """Render markdown while leaving embedded LaTeX ($...$ / $$...$$) untouched.

    python-markdown's backslash-escaping (e.g. `\\!`, `\\{`) and underscore
    handling both corrupt raw LaTeX if it's run through markdown directly, so
    math spans are stashed behind placeholders, markdown runs on everything
    else, then the original math text is restored verbatim.
    """
    if not value:
        return ''

    text = str(value)
    math_spans = []

    def _stash(m):
        math_spans.append(m.group(0))
        return f'\x00MATH{len(math_spans) - 1}\x00'

    protected = _MATH_RE.sub(_stash, text)
    html = md.markdown(protected, extensions=['fenced_code', 'tables'])

    def _restore(m):
        return escape(math_spans[int(m.group(1))])

    html = _PLACEHOLDER_RE.sub(_restore, html)
    return mark_safe(html)
