import threading
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CompanyProfile, ServiceProduct

logger = logging.getLogger(__name__)


def _run_in_thread(fn):
    threading.Thread(target=fn, daemon=True).start()


@receiver(post_save, sender=CompanyProfile)
def index_company_profile(sender, instance, **kwargs):
    def _ingest():
        try:
            from .pipeline.agents.ingestion import ingest_scope_data
            client_id = f"company_{instance.pk}"
            ingest_scope_data(client_id, 'about', 'Company About', instance.about)
            CompanyProfile.objects.filter(pk=instance.pk).update(rag_indexed=True)
            logger.info("RAG indexed CompanyProfile %s", instance.pk)
        except Exception:
            logger.exception("RAG indexing failed for CompanyProfile %s", instance.pk)
    _run_in_thread(_ingest)


@receiver(post_save, sender=ServiceProduct)
def index_service_product(sender, instance, **kwargs):
    def _ingest():
        try:
            from .pipeline.agents.ingestion import ingest_scope_data
            client_id = f"company_{instance.company_id}"
            ingest_scope_data(
                client_id,
                f"service_{instance.pk}",
                instance.name,
                instance.description,
            )
            logger.info("RAG indexed ServiceProduct %s", instance.pk)
        except Exception:
            logger.exception("RAG indexing failed for ServiceProduct %s", instance.pk)
    _run_in_thread(_ingest)
