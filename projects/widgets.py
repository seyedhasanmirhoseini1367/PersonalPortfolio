import json
from django import forms
from django.utils.safestring import mark_safe


class EditorJsWidget(forms.Widget):
    """
    Renders an Editor.js block editor in Django admin.
    Stores/returns JSON (the full Editor.js save() output).
    """

    # CDN URLs are absolute so Django won't prepend STATIC_URL.
    class Media:
        js = (
            'https://cdn.jsdelivr.net/npm/@editorjs/editorjs@2.30.7/dist/editorjs.umd.min.js',
            'https://cdn.jsdelivr.net/npm/@editorjs/header@2.8.8/dist/header.umd.min.js',
            'https://cdn.jsdelivr.net/npm/@editorjs/image@2.10.1/dist/image.umd.min.js',
            'https://cdn.jsdelivr.net/npm/@editorjs/list@1.10.0/dist/list.umd.min.js',
            'https://cdn.jsdelivr.net/npm/@editorjs/code@2.9.3/dist/code.umd.min.js',
            'https://cdn.jsdelivr.net/npm/@editorjs/embed@2.7.4/dist/embed.umd.min.js',
            'https://cdn.jsdelivr.net/npm/@editorjs/quote@2.7.6/dist/quote.umd.min.js',
        )

    def render(self, name, value, attrs=None, renderer=None):
        # value comes from forms.JSONField.prepare_value → JSON string or None
        if not value or value in ('null', 'None', '{}'):
            json_str = '{}'
        elif isinstance(value, dict):
            json_str = json.dumps(value)
        else:
            json_str = value  # already a JSON string

        field_id = (attrs or {}).get('id', f'id_{name}')
        editor_div_id = f'editorjs_holder_{name}'
        upload_url = '/projects/upload-image/'

        html = f"""
<div id="{editor_div_id}"
     style="border:1px solid #ccc; border-radius:4px; min-height:250px;
            padding:4px; background:#fff; font-family:sans-serif;"></div>
<textarea name="{name}" id="{field_id}" style="display:none;"></textarea>
<script>
(function () {{
    var DATA   = {json_str};
    var holder = '{editor_div_id}';
    var taId   = '{field_id}';
    var uploadUrl = '{upload_url}';

    function getCsrfToken() {{
        var name = 'csrftoken';
        var cookies = document.cookie.split(';');
        for (var i = 0; i < cookies.length; i++) {{
            var c = cookies[i].trim();
            if (c.indexOf(name + '=') === 0) return c.substring(name.length + 1);
        }}
        return '';
    }}

    function init() {{
        if (typeof EditorJS === 'undefined') {{
            setTimeout(init, 80);
            return;
        }}

        var editor = new EditorJS({{
            holder: holder,
            data: DATA,
            placeholder: 'Click here and start typing. Use + to add blocks…',
            tools: {{
                header: {{
                    class: Header,
                    config: {{ levels: [2, 3, 4], defaultLevel: 2 }},
                }},
                image: {{
                    class: ImageTool,
                    config: {{
                        endpoints: {{ byFile: uploadUrl }},
                        additionalRequestHeaders: {{
                            'X-CSRFToken': getCsrfToken(),
                        }},
                    }},
                }},
                list: {{
                    class: List,
                    inlineToolbar: true,
                }},
                code: CodeTool,
                embed: {{
                    class: Embed,
                    config: {{
                        services: {{ youtube: true, vimeo: true, codesandbox: true, codepen: true }},
                    }},
                }},
                quote: {{
                    class: Quote,
                    inlineToolbar: true,
                }},
            }},
            onChange: function () {{
                editor.save().then(function (d) {{
                    document.getElementById(taId).value = JSON.stringify(d);
                }});
            }},
        }});

        // Sync before form submission
        var form = document.getElementById(taId).closest('form');
        if (form && !form._editorjsListenerAdded_{name}) {{
            form._editorjsListenerAdded_{name} = true;
            form.addEventListener('submit', function (e) {{
                e.preventDefault();
                editor.save().then(function (d) {{
                    document.getElementById(taId).value = JSON.stringify(d);
                    form.submit();
                }});
            }});
        }}
    }}

    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', init);
    }} else {{
        init();
    }}
}})();
</script>
"""
        return mark_safe(html)

    def value_from_datadict(self, data, files, name):
        val = data.get(name, '')
        return val if val else '{}'
