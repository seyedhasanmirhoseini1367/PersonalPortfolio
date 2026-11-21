"""Clean user-written story HTML before it is shown.

Stories are written by any signed-in user in a rich-text editor and shown on
public pages, so their HTML must not be able to run scripts. nh3 (a Rust HTML
sanitiser) keeps the formatting the editor produces and drops everything else:
<script>, event handlers (onerror=...), javascript: links, <iframe>, styles.
"""
import nh3

ALLOWED_TAGS = {
    'p', 'br', 'span', 'strong', 'b', 'em', 'i', 'u', 's', 'sub', 'sup',
    'h1', 'h2', 'h3', 'h4', 'blockquote', 'pre', 'code',
    'ul', 'ol', 'li', 'a', 'img', 'hr',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
}

# Quill marks alignment, indentation, sizes and list types with classes and
# data- attributes; images carry a size hint.
_COMMON = {'class'}
ALLOWED_ATTRIBUTES = {
    '*': _COMMON,
    'a': _COMMON | {'href', 'title', 'target'},
    'img': _COMMON | {'src', 'alt', 'title', 'width', 'height', 'data-size'},
    'li': _COMMON | {'data-list'},
    'pre': _COMMON | {'spellcheck'},
    'td': _COMMON | {'colspan', 'rowspan'},
    'th': _COMMON | {'colspan', 'rowspan'},
}


def clean_html(value: str) -> str:
    if not value:
        return ''
    return nh3.clean(
        str(value),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={'http', 'https', 'mailto'},
        link_rel='noopener noreferrer nofollow',
    )
