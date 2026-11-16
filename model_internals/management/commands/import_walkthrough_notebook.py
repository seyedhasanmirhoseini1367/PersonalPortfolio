import base64
import hashlib
import json
import re

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from model_internals.models import Walkthrough, WalkthroughBlock


def _cell_source(cell):
    src = cell.get('source', '')
    if isinstance(src, list):
        return ''.join(src)
    return src or ''


def _stream_text(outputs):
    parts = []
    for out in outputs:
        if out.get('output_type') == 'stream' and out.get('name') == 'stdout':
            text = out.get('text', '')
            parts.append(''.join(text) if isinstance(text, list) else text)
    return ''.join(parts).strip()


MOTION_MIME = 'application/vnd.hmw.motion+json'


def _visual_outputs(outputs):
    """PNG plots and motion scenes, in the order the cell produced them.

    Yields ('png', base64_str) or ('motion', spec_dict).
    """
    for out in outputs:
        if out.get('output_type') in ('display_data', 'execute_result'):
            data = out.get('data', {})
            spec = data.get(MOTION_MIME)
            if spec:
                if isinstance(spec, str):
                    spec = json.loads(spec)
                yield 'motion', spec
                continue
            png = data.get('image/png')
            if png:
                yield 'png', ''.join(png) if isinstance(png, list) else png


class Command(BaseCommand):
    help = (
        'Import a Jupyter notebook into a Walkthrough for the "How Models Work" section. '
        'Only markdown text and cell OUTPUTS (printed numbers, plots, motion scenes) are imported — '
        'no source code is ever stored.'
    )

    def add_arguments(self, parser):
        parser.add_argument('notebook_path', type=str)
        parser.add_argument('--title', type=str, required=True)
        parser.add_argument('--slug', type=str, default='')
        parser.add_argument('--tagline', type=str, default='')
        parser.add_argument('--summary', type=str, default='')
        parser.add_argument('--category', type=str, default='other',
                             choices=[c for c, _ in Walkthrough.CATEGORY_CHOICES])
        parser.add_argument('--difficulty', type=str, default='intermediate',
                             choices=[c for c, _ in Walkthrough.DIFFICULTY_CHOICES])
        parser.add_argument('--icon', type=str, default='')
        parser.add_argument('--order', type=int, default=0)
        parser.add_argument('--unpublish', action='store_true',
                             help='Import as a draft (is_published=False)')
        parser.add_argument('--if-empty', action='store_true',
                             help='Skip only if this walkthrough already has blocks AND the '
                                  'notebook is unchanged since it was imported. Used on '
                                  'deploy: restarts are a no-op, but an edited notebook is '
                                  'picked up.')

    def handle(self, *args, **options):
        path = options['notebook_path']
        try:
            with open(path, 'r', encoding='utf-8') as f:
                nb = json.load(f)
        except OSError as e:
            raise CommandError(f'Could not read notebook: {e}')

        slug = options['slug'] or slugify(options['title'])

        with open(path, 'rb') as fb:
            fingerprint = hashlib.sha256(fb.read()).hexdigest()

        if options['if_empty']:
            existing = Walkthrough.objects.filter(slug=slug).first()
            if existing and existing.blocks.exists():
                if existing.source_fingerprint == fingerprint:
                    self.stdout.write(
                        f'"{existing.title}" is up to date '
                        f'({existing.blocks.count()} blocks) - skipping.')
                    return
                self.stdout.write(
                    f'"{existing.title}" exists but the notebook has changed '
                    f'- re-importing.')

        with transaction.atomic():
            walkthrough, _ = Walkthrough.objects.update_or_create(
                slug=slug,
                defaults=dict(
                    title=options['title'],
                    tagline=options['tagline'],
                    summary=options['summary'],
                    category=options['category'],
                    difficulty=options['difficulty'],
                    icon=options['icon'],
                    order=options['order'],
                    is_published=not options['unpublish'],
                    source_fingerprint=fingerprint,
                ),
            )
            # Idempotent re-import: wipe existing blocks and rebuild.
            #
            # Delete the image FILES too, not just the rows. Django never
            # removes the file behind an ImageField, and every re-import writes
            # fresh copies under new suffixed names -- so without this each run
            # leaves its entire set of plots behind for good. Left unchecked
            # this reached 1,443 orphaned files and 80 MB against 116 live ones.
            for _blk in walkthrough.blocks.exclude(image=''):
                if _blk.image:
                    _blk.image.delete(save=False)
            walkthrough.blocks.all().delete()

            order = 0
            created = 0
            for cell in nb.get('cells', []):
                cell_type = cell.get('cell_type')
                source = _cell_source(cell).strip()

                if cell_type == 'markdown':
                    if not source:
                        continue
                    order += 1
                    WalkthroughBlock.objects.create(
                        walkthrough=walkthrough, order=order,
                        block_type=WalkthroughBlock.TEXT, content=source,
                    )
                    created += 1

                elif cell_type == 'code':
                    outputs = cell.get('outputs', [])
                    text = _stream_text(outputs)
                    visuals = list(_visual_outputs(outputs))

                    if text:
                        order += 1
                        WalkthroughBlock.objects.create(
                            walkthrough=walkthrough, order=order,
                            block_type=WalkthroughBlock.OUTPUT, content=text,
                        )
                        created += 1

                    for kind, payload in visuals:
                        order += 1
                        if kind == 'motion':
                            WalkthroughBlock.objects.create(
                                walkthrough=walkthrough, order=order,
                                block_type=WalkthroughBlock.MOTION,
                                content=json.dumps(payload, separators=(',', ':')),
                                caption=str(payload.get('caption', ''))[:300],
                            )
                            created += 1
                            continue
                        png_b64 = payload
                        block = WalkthroughBlock(
                            walkthrough=walkthrough, order=order,
                            block_type=WalkthroughBlock.IMAGE,
                        )
                        block.image.save(
                            f'{slug}-{order}.png',
                            ContentFile(base64.b64decode(png_b64)),
                            save=False,
                        )
                        block.save()
                        created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Imported "{walkthrough.title}" ({slug}) — {created} blocks. '
            f'View at /how-models-work/{slug}/'
        ))
