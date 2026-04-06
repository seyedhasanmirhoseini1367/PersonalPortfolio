/* stories/static/stories/admin_quill.js
   Injects Quill rich-text editors into the Story admin change form.
   Loaded via StoryAdmin.Media — Quill itself is loaded before this file. */

(function () {
    'use strict';

    const FULL_TOOLBAR = [
        [{ header: [1, 2, 3, false] }],
        ['bold', 'italic', 'underline', 'strike'],
        [{ color: [] }, { background: [] }],
        [{ align: [] }],
        ['blockquote', 'code-block'],
        [{ list: 'ordered' }, { list: 'bullet' }],
        ['link', 'image'],
        ['clean'],
    ];

    const EXCERPT_TOOLBAR = [
        ['bold', 'italic', 'underline'],
        ['link'],
        ['clean'],
    ];

    const IMG_SIZES = [
        { label: 'S',  value: 'small',  pct: '30%',  title: 'Small (30%)' },
        { label: 'M',  value: 'medium', pct: '55%',  title: 'Medium (55%)' },
        { label: 'L',  value: 'large',  pct: '80%',  title: 'Large (80%)' },
        { label: '↔', value: 'full',   pct: '100%', title: 'Full width' },
    ];

    /* ── CSRF helper ─────────────────────────────────────────────────────── */
    function getCsrf() {
        const m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    /* ── Image upload handler (reused for both editors) ──────────────────── */
    function makeImageHandler(quillInstance) {
        return function () {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = 'image/jpeg,image/png,image/gif,image/webp';
            input.click();

            input.onchange = async function () {
                const file = input.files[0];
                if (!file) return;
                if (file.size > 5 * 1024 * 1024) {
                    alert('Image must be smaller than 5 MB.'); return;
                }

                const range = quillInstance.getSelection(true);
                quillInstance.insertText(range.index, '⏳ Uploading…', 'user');

                const fd = new FormData();
                fd.append('image', file);

                const uploadUrl = '/stories/editor/image-upload/';

                try {
                    const res  = await fetch(uploadUrl, {
                        method: 'POST',
                        headers: { 'X-CSRFToken': getCsrf() },
                        body: fd,
                    });
                    const data = await res.json();
                    if (data.url) {
                        quillInstance.deleteText(range.index, '⏳ Uploading…'.length);
                        quillInstance.insertEmbed(range.index, 'image', data.url, 'user');
                        quillInstance.setSelection(range.index + 1, 0);
                    } else {
                        quillInstance.deleteText(range.index, '⏳ Uploading…'.length);
                        alert('Upload failed: ' + (data.error || 'Unknown'));
                    }
                } catch (e) {
                    quillInstance.deleteText(range.index, '⏳ Uploading…'.length);
                    alert('Upload error: ' + e.message);
                }
            };
        };
    }

    /* ── Image resize toolbar ────────────────────────────────────────────── */
    function attachResizeBar(editorEl, textarea) {
        const bar = document.createElement('div');
        bar.className = 'ql-img-resize-bar';
        bar.style.cssText = [
            'position:absolute;z-index:9999;background:#1e293b;border-radius:6px;',
            'padding:4px 6px;display:none;gap:4px;box-shadow:0 4px 12px rgba(0,0,0,.4);',
        ].join('');
        IMG_SIZES.forEach(s => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.textContent = s.label;
            btn.title = s.title;
            btn.dataset.size = s.value;
            btn.style.cssText = [
                'background:transparent;border:1px solid #475569;color:#e2e8f0;',
                'border-radius:4px;padding:2px 8px;font-size:.7rem;cursor:pointer;',
            ].join('');
            btn.onmouseover = () => { btn.style.background = '#2563eb'; btn.style.borderColor = '#2563eb'; };
            btn.onmouseout  = () => {
                btn.style.background  = btn.classList.contains('active') ? '#2563eb' : 'transparent';
                btn.style.borderColor = btn.classList.contains('active') ? '#2563eb' : '#475569';
            };
            bar.appendChild(btn);
        });
        document.body.appendChild(bar);

        let activeImg = null;

        function showBar(img) {
            activeImg = img;
            const rect = img.getBoundingClientRect();
            bar.style.top  = (window.scrollY + rect.top - 38) + 'px';
            bar.style.left = (window.scrollX + rect.left)     + 'px';
            bar.style.display = 'flex';
            bar.querySelectorAll('button').forEach(b => {
                const on = b.dataset.size === (img.dataset.size || '');
                b.classList.toggle('active', on);
                b.style.background  = on ? '#2563eb' : 'transparent';
                b.style.borderColor = on ? '#2563eb' : '#475569';
            });
        }

        editorEl.addEventListener('click', e => {
            if (e.target.tagName === 'IMG') {
                showBar(e.target);
            } else {
                bar.style.display = 'none';
                activeImg = null;
            }
        });

        bar.addEventListener('click', e => {
            const btn = e.target.closest('button');
            if (!btn || !activeImg) return;
            const s = IMG_SIZES.find(x => x.value === btn.dataset.size);
            if (!s) return;
            activeImg.dataset.size = s.value;
            activeImg.style.maxWidth = s.pct;
            activeImg.style.width    = s.pct;
            showBar(activeImg);
            if (textarea) textarea.dispatchEvent(new Event('change'));
        });

        document.addEventListener('scroll', () => { bar.style.display = 'none'; }, true);
    }

    /* ── Mount a Quill editor over a textarea ────────────────────────────── */
    function mountQuill(textarea, toolbarOptions, placeholder) {
        if (!textarea) return null;

        const wrapper = document.createElement('div');
        wrapper.style.cssText = 'margin-bottom: 8px;';
        textarea.parentNode.insertBefore(wrapper, textarea);
        textarea.style.display = 'none';

        const mountDiv = document.createElement('div');
        mountDiv.style.cssText = 'background: white;';
        wrapper.appendChild(mountDiv);

        const quill = new Quill(mountDiv, {
            theme: 'snow',
            placeholder: placeholder || '',
            modules: {
                toolbar: {
                    container: toolbarOptions,
                    handlers: { image: null },
                },
            },
        });

        const hasImage = toolbarOptions.some(
            row => Array.isArray(row) && row.includes('image')
        );
        if (hasImage) {
            quill.getModule('toolbar').addHandler('image', makeImageHandler(quill));
            /* attach resize bar to this editor's root element */
            attachResizeBar(quill.root, textarea);
        }

        /* Load existing content */
        const val = textarea.value.trim();
        if (val) {
            if (val.startsWith('<')) {
                quill.clipboard.dangerouslyPasteHTML(val);
            } else {
                quill.setText(val);
            }
        }

        /* Sync to textarea on every change */
        quill.on('text-change', function () {
            textarea.value = quill.getSemanticHTML();
        });

        return quill;
    }

    /* ── Inline styles injected once ─────────────────────────────────────── */
    function injectStyles() {
        if (document.getElementById('admin-quill-styles')) return;
        const style = document.createElement('style');
        style.id = 'admin-quill-styles';
        style.textContent = `
            .ql-toolbar.ql-snow {
                border: 1px solid #ccc;
                border-radius: 4px 4px 0 0;
                background: #f8fafc;
                flex-wrap: wrap;
            }
            .ql-container.ql-snow {
                border: 1px solid #ccc;
                border-top: none;
                border-radius: 0 0 4px 4px;
            }
            #id_content + div .ql-editor,
            [data-quill="content"] .ql-editor { min-height: 380px; }

            #id_excerpt + div .ql-editor,
            [data-quill="excerpt"] .ql-editor { min-height: 100px; max-height: 200px; }

            .ql-editor img {
                max-height: 180px;
                width: auto;
                max-width: 100%;
                border-radius: 4px;
                border: 1px solid #e2e8f0;
                cursor: pointer;
                display: block;
                margin: 6px 0;
            }
            .ql-editor img:hover { border-color: #2563eb; }

            .ql-editor blockquote {
                border-left: 4px solid #2563eb;
                padding-left: 1rem;
                color: #64748b;
                font-style: italic;
            }
            .ql-editor pre.ql-syntax {
                background: #1e1e2e;
                color: #e2e8f0;
                border-radius: 4px;
                font-size: .875em;
            }
        `;
        document.head.appendChild(style);
    }

    /* ── Entry point ──────────────────────────────────────────────────────── */
    function init() {
        if (typeof Quill === 'undefined') return;
        injectStyles();

        const contentTextarea = document.getElementById('id_content');
        const excerptTextarea = document.getElementById('id_excerpt');

        const quillContent = mountQuill(
            contentTextarea,
            FULL_TOOLBAR,
            'Write the full story here…'
        );

        mountQuill(
            excerptTextarea,
            EXCERPT_TOOLBAR,
            'Short excerpt shown in story listings…'
        );

        /* Final sync on admin Save buttons */
        const form = document.querySelector('#content-main form, form[method="post"]');
        if (form && quillContent) {
            form.addEventListener('submit', function () {
                if (contentTextarea) {
                    contentTextarea.value = quillContent.getSemanticHTML();
                }
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
