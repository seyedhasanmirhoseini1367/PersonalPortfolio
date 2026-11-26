"""Turning uploads into lesson text, one extractor per kind of file.

Each extractor has two halves:
  prepare(upload) - runs in the request: checks the file and returns the bytes to queue
                    (raises ValueError with a message the learner can act on)
  extract(data, n, subject) - runs in the background build: returns [(label, text), ...],
                    where label says where the text came from ("Page 3", "Photo 2")

Adding a format (web page, audio, subtitles) means one more class in EXTRACTORS.
Uploaded files are untrusted data: they are only ever read as text to study.
"""
import io
import re

MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_PDF_PAGES = 40
MIN_PAGE_CHARS = 40     # a PDF page with less text than this is probably a scan


class Extractor:
    kind = ''
    label = ''
    extensions = ()
    mime_prefixes = ()

    def accepts(self, name, content_type):
        name, content_type = (name or '').lower(), (content_type or '').lower()
        return name.endswith(self.extensions) or any(content_type.startswith(m) for m in self.mime_prefixes)

    def prepare(self, upload):
        if upload.size > MAX_FILE_BYTES:
            raise ValueError(f'“{upload.name}” is over 12 MB.')
        return upload.read()

    def extract(self, data, n, subject):
        raise NotImplementedError


class ImageExtractor(Extractor):
    kind, label = 'image', 'Photo'
    extensions = ('.jpg', '.jpeg', '.png', '.webp', '.heic', '.gif')
    mime_prefixes = ('image/',)

    def prepare(self, upload):
        from .pipeline import prepare_image
        raw = super().prepare(upload)
        try:
            return prepare_image(raw)
        except Exception:
            raise ValueError(f'“{upload.name}” could not be opened as an image. Try a JPG or PNG.')

    def extract(self, data, n, subject):
        from .pipeline import read_images
        return [(f'Photo {n}', read_images([data], subject.read_prompt))]


class PDFExtractor(Extractor):
    kind, label = 'pdf', 'PDF'
    extensions = ('.pdf',)
    mime_prefixes = ('application/pdf',)

    def prepare(self, upload):
        raw = super().prepare(upload)
        if not raw.startswith(b'%PDF'):
            raise ValueError(f'“{upload.name}” is not a PDF file.')
        try:
            from pypdf import PdfReader
            pages = len(PdfReader(io.BytesIO(raw)).pages)
        except Exception:
            raise ValueError(f'“{upload.name}” could not be opened. It may be damaged or password-protected.')
        if pages > MAX_PDF_PAGES:
            raise ValueError(f'“{upload.name}” has {pages} pages. Send at most {MAX_PDF_PAGES} pages at a time '
                             '(split the document into chapters).')
        return raw

    def extract(self, data, n, subject):
        from pypdf import PdfReader
        pages = [(p.extract_text() or '').strip() for p in PdfReader(io.BytesIO(data)).pages]
        if pages and sum(len(p) >= MIN_PAGE_CHARS for p in pages) >= len(pages) / 2:
            return [(f'Page {i}', clean(t)) for i, t in enumerate(pages, 1) if t]
        # Mostly scanned pages: let the vision model read the PDF itself.
        from .pipeline import read_pdf
        text = read_pdf(data, subject.read_prompt + ' Start every page with a line "=== Page N ===".')
        return split_pages(text)


class DOCXExtractor(Extractor):
    kind, label = 'docx', 'Word document'
    extensions = ('.docx',)
    mime_prefixes = ('application/vnd.openxmlformats-officedocument.wordprocessingml',)

    def prepare(self, upload):
        raw = super().prepare(upload)
        try:
            import docx
            docx.Document(io.BytesIO(raw))
        except Exception:
            raise ValueError(f'“{upload.name}” could not be opened as a Word (.docx) document.')
        return raw

    def extract(self, data, n, subject):
        import docx
        doc = docx.Document(io.BytesIO(data))
        parts, section, buf = [], "", []

        def flush():
            if buf:
                parts.append((section or f'Part {len(parts) + 1}', '\n'.join(buf)))
                buf.clear()
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            if (para.style.name or '').lower().startswith(('heading', 'title')):
                flush()
                section = text[:50]
                count = 0
            buf.append(text)
        flush()
        for t, table in enumerate(doc.tables, 1):
            rows = [' | '.join(c.text.strip() for c in row.cells) for row in table.rows]
            if any(r.strip(' |') for r in rows):
                parts.append((f'Table {t}', '\n'.join(rows)))
        return parts


class TextExtractor(Extractor):
    """Typed or pasted text: split on blank lines into paragraphs."""
    kind, label = 'text', 'Text'

    def accepts(self, name, content_type):
        return False   # never chosen for a file; used directly for the text box

    def extract(self, data, n, subject):
        text = data.decode('utf-8') if isinstance(data, bytes) else data
        paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
        return [(f'Paragraph {i}', p) for i, p in enumerate(paras, 1)]


EXTRACTORS = {e.kind: e for e in (ImageExtractor(), PDFExtractor(), DOCXExtractor(), TextExtractor())}
FILE_TYPES = '.jpg,.jpeg,.png,.webp,.heic,.pdf,.docx,image/*,application/pdf'


def for_file(name, content_type):
    for e in EXTRACTORS.values():
        if e.accepts(name, content_type):
            return e
    return None


def clean(text):
    text = text.replace('\x00', '')
    text = re.sub(r'[ \t]+\n', '\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def split_marked(text, word):
    """Split text the vision model marked with "=== <word> N ===" lines into [(N, body)]."""
    chunks = re.split(r'^\s*=+\s*' + word + r'\s+(\d+)\s*=+\s*$', text or '', flags=re.M | re.I)
    out = []
    for i in range(1, len(chunks) - 1, 2):
        body = clean(chunks[i + 1])
        if body:
            out.append((chunks[i], body))
    return out


def split_pages(text):
    found = split_marked(text, 'Page')
    if not found:
        return [('Page 1', clean(text))] if (text or '').strip() else []
    return [(f'Page {n}', body) for n, body in found]
