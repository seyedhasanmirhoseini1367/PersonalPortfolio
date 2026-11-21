"""Embed RAG chunks that have no usable vector.

A chunk is re-embedded when its stored vector is missing, all zeros (what the
embedding service saves when the API call fails, e.g. a retired model), a
different length, or made by a different embedding model than the current one. Safe to run on every start-up: chunks
that already have a good vector are skipped, and it stops early if the API
still fails so it does not burn the free quota.
"""
import pickle

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand

from rag_system.models import DocumentChunk
from rag_system.services.embedding_service import EmbeddingService, _EMBED_DIM


def needs_embedding(blob, metadata=None) -> bool:
    if metadata is not None and (metadata or {}).get('embedding_model') != settings.RAG_CONFIG['EMBEDDING_MODEL']:
        return True
    if not blob:
        return True
    try:
        vec = np.asarray(pickle.loads(bytes(blob)), dtype=np.float32)
    except Exception:
        return True
    return vec.shape != (_EMBED_DIM,) or not np.any(vec)


class Command(BaseCommand):
    help = 'Embed RAG chunks whose vector is missing or zero.'

    def add_arguments(self, parser):
        parser.add_argument('--batch', type=int, default=20)

    def handle(self, *args, **options):
        todo = [c for c in DocumentChunk.objects.only('id', 'content', 'embedding', 'metadata')
                if needs_embedding(c.embedding, c.metadata)]
        if not todo:
            self.stdout.write('embed_missing: all chunks have vectors.')
            return
        self.stdout.write(f'embed_missing: {len(todo)} chunk(s) to embed...')
        service, done = EmbeddingService(), 0
        for start in range(0, len(todo), options['batch']):
            batch = todo[start:start + options['batch']]
            service.embed_document_chunks(batch)
            ok = sum(not needs_embedding(DocumentChunk.objects.get(pk=c.pk).embedding) for c in batch)
            done += ok
            if ok == 0:
                self.stdout.write(self.style.WARNING('embed_missing: the embedding API is failing; stopping.'))
                break
        self.stdout.write(f'embed_missing: embedded {done} of {len(todo)} chunk(s).')
