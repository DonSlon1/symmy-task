import logging
import time

from django.conf import settings
from django.utils import timezone

from integrator.models import ProductSyncState
from integrator.transforms import validate_product, transform_product, deduplicate, compute_hash

logger = logging.getLogger(__name__)

RATE_LIMIT = getattr(settings, 'ESHOP_API_RATE_LIMIT', 5)


class SyncOrchestrator:
    def __init__(self, source, client):
        self.source = source
        self.client = client

    def run(self):
        logger.info("Starting product sync")

        raw_data = self.source.load()
        raw_data = deduplicate(raw_data)

        session = self.client.make_session()

        stats = {'synced': 0, 'skipped_unchanged': 0, 'skipped_invalid': 0, 'errors': 0}
        interval = 1.0 / RATE_LIMIT

        valid_products = []
        for raw in raw_data:
            is_valid, reason = validate_product(raw)
            if not is_valid:
                logger.warning("Skipping invalid product: %s", reason)
                stats['skipped_invalid'] += 1
                continue
            payload = transform_product(raw)
            data_hash = compute_hash(payload)
            valid_products.append((payload, data_hash))

        # Bulk fetch existing sync states (1 query instead of N)
        all_skus = [p['sku'] for p, _ in valid_products]
        existing_states = {
            state.sku: state
            for state in ProductSyncState.objects.filter(sku__in=all_skus)
        }

        to_create = []
        to_update = []
        now = timezone.now()

        for payload, data_hash in valid_products:
            sku = payload['sku']
            existing = existing_states.get(sku)

            if existing and existing.data_hash == data_hash:
                logger.debug("Product %s unchanged, skipping", sku)
                stats['skipped_unchanged'] += 1
                continue

            is_update = existing is not None

            try:
                time.sleep(interval)
                self.client.send(session, payload, is_update=is_update)

                if is_update:
                    existing.data_hash = data_hash
                    existing.last_synced_at = now
                    to_update.append(existing)
                else:
                    to_create.append(
                        ProductSyncState(sku=sku, data_hash=data_hash, last_synced_at=now)
                    )

                stats['synced'] += 1
                logger.info("Synced %s (%s)", sku, "updated" if is_update else "created")
            except Exception as exc:
                logger.error("Failed to sync %s: %s", sku, exc)
                stats['errors'] += 1

        # Bulk DB writes (2 queries instead of N)
        if to_create:
            ProductSyncState.objects.bulk_create(to_create)
        if to_update:
            ProductSyncState.objects.bulk_update(to_update, ['data_hash', 'last_synced_at'])

        logger.info("Sync complete: %s", stats)
        return stats
