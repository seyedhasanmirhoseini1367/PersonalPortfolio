import json
from django import template
from django.utils.safestring import mark_safe
from django.utils.html import escape

register = template.Library()


def _render_block(block):
    btype = block.get('type', '')
    data  = block.get('data', {})

    if btype == 'paragraph':
        text = data.get('text', '')
        return f'<p class="ejs-paragraph">{text}</p>'

    if btype == 'header':
        level = data.get('level', 2)
        text  = data.get('text', '')
        return f'<h{level} class="ejs-header">{text}</h{level}>'

    if btype == 'image':
        file_data  = data.get('file', {})
        url        = escape(file_data.get('url', ''))
        caption    = data.get('caption', '')
        stretched  = data.get('stretched', False)
        with_bg    = data.get('withBackground', False)
        with_border = data.get('withBorder', False)
        cls = 'ejs-image'
        if stretched:   cls += ' ejs-image--stretched'
        if with_bg:     cls += ' ejs-image--bg'
        if with_border: cls += ' ejs-image--bordered'
        cap_html = f'<figcaption class="ejs-image-caption">{caption}</figcaption>' if caption else ''
        return (
            f'<figure class="{cls}">'
            f'<img src="{url}" alt="{escape(caption)}" loading="lazy">'
            f'{cap_html}'
            f'</figure>'
        )

    if btype == 'list':
        style = data.get('style', 'unordered')
        items = data.get('items', [])
        tag   = 'ol' if style == 'ordered' else 'ul'
        items_html = ''.join(f'<li>{item}</li>' for item in items)
        return f'<{tag} class="ejs-list">{items_html}</{tag}>'

    if btype == 'code':
        code = escape(data.get('code', ''))
        return f'<pre class="ejs-code"><code>{code}</code></pre>'

    if btype == 'embed':
        embed_url = escape(data.get('embed', ''))
        caption   = data.get('caption', '')
        height    = data.get('height', 320)
        cap_html  = f'<figcaption class="ejs-image-caption">{caption}</figcaption>' if caption else ''
        return (
            f'<figure class="ejs-embed">'
            f'<iframe src="{embed_url}" height="{height}" '
            f'frameborder="0" allowfullscreen style="width:100%;border-radius:8px;"></iframe>'
            f'{cap_html}'
            f'</figure>'
        )

    if btype == 'quote':
        text      = data.get('text', '')
        caption   = data.get('caption', '')
        alignment = data.get('alignment', 'left')
        cite_html = f'<cite class="ejs-quote-cite">{caption}</cite>' if caption else ''
        return (
            f'<blockquote class="ejs-quote" style="text-align:{alignment}">'
            f'{text}{cite_html}'
            f'</blockquote>'
        )

    # Unknown block type — skip silently
    return ''


@register.filter(name='render_editorjs', is_safe=True)
def render_editorjs(value):
    """
    Convert an Editor.js JSON dict (or JSON string) to safe HTML.
    Usage: {{ project.description_rich|render_editorjs }}
    """
    if not value:
        return ''

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return mark_safe(f'<p>{escape(value)}</p>')

    if not isinstance(value, dict):
        return ''

    blocks = value.get('blocks', [])
    parts  = [_render_block(b) for b in blocks]
    return mark_safe('\n'.join(p for p in parts if p))
