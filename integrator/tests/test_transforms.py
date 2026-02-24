from django.test import TestCase

from integrator.transforms import validate_product, transform_product, deduplicate, compute_hash


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
