import logging
import time

import requests
from django.conf import settings

from .base import BaseClient

logger = logging.getLogger(__name__)

ESHOP_BASE_URL = getattr(settings, 'ESHOP_API_BASE_URL', 'https://api.fake-eshop.cz/v1')
ESHOP_API_KEY = getattr(settings, 'ESHOP_API_KEY', 'symma-secret-token')

MAX_RETRIES = 5
RETRY_BASE_DELAY = 1.0


class EshopClient(BaseClient):
    def make_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            'X-Api-Key': ESHOP_API_KEY,
            'Content-Type': 'application/json',
        })
        return session

    def send(self, session, payload, is_update=False):
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
