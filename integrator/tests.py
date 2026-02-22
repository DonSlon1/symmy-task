import json
import os
import tempfile

import responses
from unittest.mock import patch

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
from integrator.models import ProductSyncState


def _make_session():
    import requests
    s = requests.Session()
    s.headers.update({
        'X-Api-Key': 'symma-secret-token',
        'Content-Type': 'application/json',
    })
    return s


def _valid_raw_product():
    return {
        "id": "SKU-001",
        "title": "Kávovar Espresso",
        "price_vat_excl": 12400.50,
        "stocks": {"praha": 5, "brno": 3},
        "attributes": {"color": "stříbrná"},
    }


def _erp_data():
    return [
        {"id": "SKU-001", "title": "Kávovar Espresso", "price_vat_excl": 12400.50,
         "stocks": {"praha": 5, "brno": 3}, "attributes": {"color": "stříbrná"}},
        {"id": "SKU-002", "title": "Sleva - chyba", "price_vat_excl": -150.0,
         "stocks": {"praha": 10}, "attributes": {}},
        {"id": "SKU-003", "title": "Mlýnek", "price_vat_excl": 1500,
         "stocks": {"externi": 50}, "attributes": None},
        {"id": "SKU-004", "title": "Hrnek", "price_vat_excl": None,
         "stocks": {"praha": 10}, "attributes": {"color": "černá"}},
        {"id": "SKU-006", "title": "Tablety", "price_vat_excl": 250,
         "stocks": {"praha": 100}, "attributes": {}},
        {"id": "SKU-006", "title": "Tablety", "price_vat_excl": 250,
         "stocks": {"praha": 100}, "attributes": {}},
        {"id": "SKU-008", "title": "Filtry", "price_vat_excl": 300,
         "stocks": {"praha": "N/A"}, "attributes": {"color": "bílá"}},
    ]


class TestValidation(TestCase):
    def test_valid_product(self):
        is_valid, reason = validate_product(_valid_raw_product())
        self.assertTrue(is_valid)
        self.assertEqual(reason, "")

    def test_null_price_is_invalid(self):
        product = {"id": "SKU-004", "price_vat_excl": None, "stocks": {"a": 1}}
        is_valid, reason = validate_product(product)
        self.assertFalse(is_valid)
        self.assertIn("null price", reason)

    def test_negative_price_is_invalid(self):
        product = {"id": "SKU-002", "price_vat_excl": -150.0, "stocks": {"a": 1}}
        is_valid, reason = validate_product(product)
        self.assertFalse(is_valid)
        self.assertIn("negative price", reason)

    def test_missing_sku_is_invalid(self):
        product = {"price_vat_excl": 100, "stocks": {"a": 1}}
        is_valid, reason = validate_product(product)
        self.assertFalse(is_valid)
        self.assertIn("missing SKU", reason)

    def test_missing_stocks_is_invalid(self):
        product = {"id": "X", "price_vat_excl": 100, "stocks": {}}
        is_valid, reason = validate_product(product)
        self.assertFalse(is_valid)

    def test_non_numeric_price_is_invalid(self):
        product = {"id": "SKU-X", "price_vat_excl": "free", "stocks": {"a": 1}}
        is_valid, reason = validate_product(product)
        self.assertFalse(is_valid)
        self.assertIn("non-numeric price", reason)


class TestTransformation(TestCase):
    def test_vat_calculation(self):
        result = transform_product(_valid_raw_product())
        self.assertEqual(result['price'], round(12400.50 * 1.21, 2))

    def test_stock_summation(self):
        result = transform_product(_valid_raw_product())
        self.assertEqual(result['stock'], 8)

    def test_non_numeric_stock_skipped(self):
        product = {
            "id": "SKU-008", "title": "Filtry", "price_vat_excl": 300,
            "stocks": {"praha": "N/A", "brno": 5}, "attributes": {"color": "bílá"},
        }
        result = transform_product(product)
        self.assertEqual(result['stock'], 5)

    def test_color_from_attributes(self):
        result = transform_product(_valid_raw_product())
        self.assertEqual(result['color'], "stříbrná")

    def test_missing_color_defaults_na(self):
        product = {
            "id": "SKU-006", "title": "Tablety", "price_vat_excl": 250,
            "stocks": {"praha": 100}, "attributes": {},
        }
        result = transform_product(product)
        self.assertEqual(result['color'], "N/A")

    def test_null_attributes_defaults_na(self):
        product = {
            "id": "SKU-003", "title": "Mlýnek", "price_vat_excl": 1500,
            "stocks": {"externi": 50}, "attributes": None,
        }
        result = transform_product(product)
        self.assertEqual(result['color'], "N/A")

    def test_payload_structure(self):
        result = transform_product(_valid_raw_product())
        self.assertEqual(set(result.keys()), {'sku', 'title', 'price', 'stock', 'color'})


class TestDeduplication(TestCase):
    def test_removes_duplicate_skus(self):
        deduped = deduplicate(_erp_data())
        skus = [p['id'] for p in deduped]
        self.assertEqual(skus.count('SKU-006'), 1)

    def test_keeps_last_occurrence(self):
        data = [
            {"id": "A", "title": "First"},
            {"id": "A", "title": "Second"},
        ]
        result = deduplicate(data)
        self.assertEqual(result[0]['title'], "Second")


class TestHash(TestCase):
    def test_same_data_same_hash(self):
        payload = {"sku": "X", "price": 100, "stock": 5}
        self.assertEqual(compute_hash(payload), compute_hash(payload))

    def test_different_data_different_hash(self):
        p1 = {"sku": "X", "price": 100}
        p2 = {"sku": "X", "price": 200}
        self.assertNotEqual(compute_hash(p1), compute_hash(p2))

    def test_key_order_irrelevant(self):
        p1 = {"a": 1, "b": 2}
        p2 = {"b": 2, "a": 1}
        self.assertEqual(compute_hash(p1), compute_hash(p2))


class TestApiCommunication(TestCase):
    @responses.activate
    def test_post_new_product(self):
        responses.add(
            responses.POST,
            f"{ESHOP_BASE_URL}/products/",
            json={"status": "created"},
            status=201,
        )

        session = _make_session()
        payload = {"sku": "SKU-001", "title": "Test", "price": 100, "stock": 1, "color": "N/A"}
        resp = send_to_eshop(session, payload, is_update=False)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(responses.calls[0].request.headers['X-Api-Key'], 'symma-secret-token')

    @responses.activate
    def test_patch_existing_product(self):
        responses.add(
            responses.PATCH,
            f"{ESHOP_BASE_URL}/products/SKU-001/",
            json={"status": "updated"},
            status=200,
        )

        session = _make_session()
        payload = {"sku": "SKU-001", "title": "Test", "price": 100, "stock": 1, "color": "N/A"}
        resp = send_to_eshop(session, payload, is_update=True)

        self.assertEqual(resp.status_code, 200)

    @responses.activate
    def test_retry_on_429(self):
        responses.add(
            responses.POST,
            f"{ESHOP_BASE_URL}/products/",
            json={"error": "rate limited"},
            status=429,
            headers={"Retry-After": "0.01"},
        )
        responses.add(
            responses.POST,
            f"{ESHOP_BASE_URL}/products/",
            json={"status": "created"},
            status=201,
        )

        session = _make_session()
        payload = {"sku": "SKU-001", "title": "Test", "price": 100, "stock": 1, "color": "N/A"}

        with patch('integrator.tasks.RETRY_BASE_DELAY', 0.01):
            resp = send_to_eshop(session, payload, is_update=False)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(responses.calls), 2)

    @responses.activate
    def test_429_exhausts_retries(self):
        for _ in range(5):
            responses.add(
                responses.POST,
                f"{ESHOP_BASE_URL}/products/",
                json={"error": "rate limited"},
                status=429,
                headers={"Retry-After": "0.01"},
            )

        session = _make_session()
        payload = {"sku": "SKU-001", "title": "Test", "price": 100, "stock": 1, "color": "N/A"}

        with patch('integrator.tasks.RETRY_BASE_DELAY', 0.01):
            with self.assertRaisesRegex(Exception, "Rate limit exceeded"):
                send_to_eshop(session, payload, is_update=False)


class TestDeltaSync(TestCase):
    @responses.activate
    def test_first_sync_creates_all(self):
        responses.add(
            responses.POST,
            f"{ESHOP_BASE_URL}/products/",
            json={"status": "created"},
            status=201,
        )

        with patch('integrator.tasks.load_erp_data', return_value=_erp_data()):
            with patch('integrator.tasks.time.sleep'):
                result = sync_products()

        # SKU-002 neg price, SKU-004 null price -> invalid
        self.assertEqual(result['synced'], 4)
        self.assertEqual(result['skipped_invalid'], 2)
        self.assertEqual(ProductSyncState.objects.count(), 4)

    @responses.activate
    def test_second_sync_skips_unchanged(self):
        responses.add(
            responses.POST,
            f"{ESHOP_BASE_URL}/products/",
            json={"status": "created"},
            status=201,
        )

        with patch('integrator.tasks.load_erp_data', return_value=_erp_data()):
            with patch('integrator.tasks.time.sleep'):
                sync_products()
                result = sync_products()

        self.assertEqual(result['synced'], 0)
        self.assertEqual(result['skipped_unchanged'], 4)

    @responses.activate
    def test_changed_product_gets_patched(self):
        responses.add(
            responses.POST,
            f"{ESHOP_BASE_URL}/products/",
            json={"status": "created"},
            status=201,
        )
        responses.add(
            responses.PATCH,
            f"{ESHOP_BASE_URL}/products/SKU-001/",
            json={"status": "updated"},
            status=200,
        )

        erp_data = _erp_data()
        with patch('integrator.tasks.load_erp_data', return_value=erp_data):
            with patch('integrator.tasks.time.sleep'):
                sync_products()

        modified_data = [p.copy() for p in erp_data]
        modified_data[0] = {**modified_data[0], "price_vat_excl": 13000.0}

        responses.add(
            responses.POST,
            f"{ESHOP_BASE_URL}/products/",
            json={"status": "created"},
            status=201,
        )

        with patch('integrator.tasks.load_erp_data', return_value=modified_data):
            with patch('integrator.tasks.time.sleep'):
                result = sync_products()

        self.assertEqual(result['synced'], 1)
        self.assertEqual(result['skipped_unchanged'], 3)


class TestLoadErpData(TestCase):
    def test_loads_json_from_file(self):
        data = [{"id": "SKU-TEST", "title": "Test"}]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
            tmp_path = f.name
        try:
            result = load_erp_data(tmp_path)
            self.assertEqual(result, data)
        finally:
            os.unlink(tmp_path)

    def test_loads_default_erp_file(self):
        result = load_erp_data()
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)


class TestProductSyncStateModel(TestCase):
    def test_str(self):
        state = ProductSyncState.objects.create(sku="SKU-TEST", data_hash="abc123")
        self.assertIn("SKU-TEST", str(state))


class TestSyncErrors(TestCase):
    @responses.activate
    def test_api_error_counted(self):
        responses.add(
            responses.POST,
            f"{ESHOP_BASE_URL}/products/",
            json={"error": "server error"},
            status=500,
        )

        erp_data = [
            {"id": "SKU-001", "title": "Test", "price_vat_excl": 100,
             "stocks": {"a": 1}, "attributes": {}},
        ]

        with patch('integrator.tasks.load_erp_data', return_value=erp_data):
            with patch('integrator.tasks.time.sleep'):
                result = sync_products()

        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['synced'], 0)
