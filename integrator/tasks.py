from celery import shared_task
from django.conf import settings
from django.utils.module_loading import import_string

from integrator.sync import SyncOrchestrator

# Re-exports for backward compatibility
from integrator.transforms import validate_product, transform_product, deduplicate, compute_hash  # noqa: F401
from integrator.clients.eshop_client import (  # noqa: F401
    ESHOP_BASE_URL,
    ESHOP_API_KEY,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
)


def _get_source(**kwargs):
    cls = import_string(settings.SYNC_SOURCE_CLASS)
    return cls(**kwargs)


def _get_client():
    cls = import_string(settings.SYNC_CLIENT_CLASS)
    return cls()


def load_erp_data(path=None):
    return _get_source(path=path).load()


def send_to_eshop(session, payload, is_update=False):
    return _get_client().send(session, payload, is_update=is_update)


@shared_task(max_retries=3, default_retry_delay=60)
def sync_products():
    orchestrator = SyncOrchestrator(
        source=_get_source(),
        client=_get_client(),
    )
    return orchestrator.run()
