import hashlib
import json
import logging
import time

import requests
from celery import shared_task
from django.conf import settings

from integrator.models import ProductSyncState

logger = logging.getLogger(__name__)

ESHOP_BASE_URL = getattr(settings, 'ESHOP_API_BASE_URL', 'https://api.fake-eshop.cz/v1')
ESHOP_API_KEY = getattr(settings, 'ESHOP_API_KEY', 'symma-secret-token')
RATE_LIMIT = getattr(settings, 'ESHOP_API_RATE_LIMIT', 5)

MAX_RETRIES = 5
RETRY_BASE_DELAY = 1.0


def load_erp_data(path=None):
    if path is None:
        path = settings.BASE_DIR / 'erp_data.json'
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def validate_product(raw):
    """Returns (is_valid, reason)."""
    sku = raw.get('id')
    if not sku:
        return False, "missing SKU"

    price = raw.get('price_vat_excl')
    if price is None:
        return False, f"{sku}: null price"
    if not isinstance(price, (int, float)):
        return False, f"{sku}: non-numeric price"
    if price < 0:
        return False, f"{sku}: negative price ({price})"

    stocks = raw.get('stocks')
    if not stocks or not isinstance(stocks, dict):
        return False, f"{sku}: missing or invalid stocks"

    return True, ""


def transform_product(raw):
    sku = raw['id']
    price_excl = raw['price_vat_excl']
    price_incl = round(price_excl * 1.21, 2)

    total_stock = 0
    for warehouse, qty in raw.get('stocks', {}).items():
        if isinstance(qty, (int, float)):
            total_stock += int(qty)

    attributes = raw.get('attributes') or {}
    color = attributes.get('color', 'N/A') if isinstance(attributes, dict) else 'N/A'

    return {
        'sku': sku,
        'title': raw['title'],
        'price': price_incl,
        'stock': total_stock,
        'color': color,
    }


def deduplicate(products):
    seen = {}
    for p in products:
        seen[p['id']] = p
    return list(seen.values())


def compute_hash(payload):
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def send_to_eshop(session, payload, is_update=False):
    sku = payload['sku']
    if is_update:
        url = f"{ESHOP_BASE_URL}/products/{sku}/"
        method = session.patch
    else:
        url = f"{ESHOP_BASE_URL}/products/"
        method = session.post

    for attempt in range(MAX_RETRIES):
        response = method(url, json=payload)

        if response.status_code == 429:
            retry_after = float(response.headers.get('Retry-After', RETRY_BASE_DELAY))
            delay = max(retry_after, RETRY_BASE_DELAY * (2 ** attempt))
            logger.warning(
                "Rate limited (429) for %s, attempt %d/%d, waiting %.1fs",
                sku, attempt + 1, MAX_RETRIES, delay,
            )
            time.sleep(delay)
            continue

        response.raise_for_status()
        return response

    raise requests.exceptions.HTTPError(
        f"Rate limit exceeded after {MAX_RETRIES} retries for {sku}"
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_products(self):
    logger.info("Starting product sync")

    raw_data = load_erp_data()
    raw_data = deduplicate(raw_data)

    session = requests.Session()
    session.headers.update({
        'X-Api-Key': ESHOP_API_KEY,
        'Content-Type': 'application/json',
    })

    stats = {'synced': 0, 'skipped_unchanged': 0, 'skipped_invalid': 0, 'errors': 0}
    interval = 1.0 / RATE_LIMIT

    for raw in raw_data:
        is_valid, reason = validate_product(raw)
        if not is_valid:
            logger.warning("Skipping invalid product: %s", reason)
            stats['skipped_invalid'] += 1
            continue

        payload = transform_product(raw)
        data_hash = compute_hash(payload)
        sku = payload['sku']

        try:
            sync_state = ProductSyncState.objects.get(sku=sku)
            if sync_state.data_hash == data_hash:
                logger.debug("Product %s unchanged, skipping", sku)
                stats['skipped_unchanged'] += 1
                continue
            is_update = True
        except ProductSyncState.DoesNotExist:
            sync_state = None
            is_update = False

        try:
            time.sleep(interval)
            send_to_eshop(session, payload, is_update=is_update)

            ProductSyncState.objects.update_or_create(
                sku=sku,
                defaults={'data_hash': data_hash},
            )
            stats['synced'] += 1
            logger.info("Synced %s (%s)", sku, "updated" if is_update else "created")
        except Exception as exc:
            logger.error("Failed to sync %s: %s", sku, exc)
            stats['errors'] += 1

    logger.info("Sync complete: %s", stats)
    return stats
