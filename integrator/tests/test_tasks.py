import json
import os
import tempfile

import responses
from unittest.mock import patch, MagicMock

from django.test import TestCase

from integrator.tasks import (
    load_erp_data,
    validate_product,
    transform_product,
    deduplicate,
    compute_hash,
    send_to_eshop,
    sync_products,
    ESHOP_BASE_URL,
)


class TestBackwardCompatReExports(TestCase):
    """Verify that old import paths from integrator.tasks still work."""

    def test_validate_product_reexport(self):
        result = validate_product({"id": "X", "price_vat_excl": 100, "stocks": {"a": 1}})
        self.assertTrue(result[0])

    def test_transform_product_reexport(self):
        raw = {"id": "X", "title": "T", "price_vat_excl": 100, "stocks": {"a": 1}, "attributes": {}}
        result = transform_product(raw)
        self.assertEqual(result['sku'], "X")

    def test_deduplicate_reexport(self):
        data = [{"id": "A"}, {"id": "A"}]
        self.assertEqual(len(deduplicate(data)), 1)

    def test_compute_hash_reexport(self):
        self.assertIsInstance(compute_hash({"a": 1}), str)

    def test_eshop_base_url_reexport(self):
        self.assertIn("fake-eshop", ESHOP_BASE_URL)


class TestLoadErpDataWrapper(TestCase):
    def test_load_erp_data_with_path(self):
        data = [{"id": "SKU-TEST"}]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
            tmp_path = f.name
        try:
            result = load_erp_data(tmp_path)
            self.assertEqual(result, data)
        finally:
            os.unlink(tmp_path)

    def test_load_erp_data_default(self):
        result = load_erp_data()
        self.assertIsInstance(result, list)


class TestSendToEshopWrapper(TestCase):
    @responses.activate
    def test_send_to_eshop_delegates(self):
        responses.add(
            responses.POST,
            f"{ESHOP_BASE_URL}/products/",
            json={"status": "created"},
            status=201,
        )
        import requests as req
        session = req.Session()
        session.headers.update({'X-Api-Key': 'test', 'Content-Type': 'application/json'})
        payload = {"sku": "SKU-001", "title": "T", "price": 100, "stock": 1, "color": "N/A"}
        resp = send_to_eshop(session, payload)
        self.assertEqual(resp.status_code, 201)


class TestSyncProductsTask(TestCase):
    @responses.activate
    def test_sync_products_runs(self):
        responses.add(
            responses.POST,
            f"{ESHOP_BASE_URL}/products/",
            json={"status": "created"},
            status=201,
        )

        erp_data = [
            {"id": "SKU-001", "title": "Test", "price_vat_excl": 100,
             "stocks": {"a": 1}, "attributes": {}},
        ]

        with patch('integrator.sources.json_source.JsonFileSource.load', return_value=erp_data):
            with patch('integrator.sync.time.sleep'):
                result = sync_products()

        self.assertEqual(result['synced'], 1)
