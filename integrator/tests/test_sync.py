import responses
from unittest.mock import patch, MagicMock

from django.test import TestCase

from integrator.clients.eshop_client import EshopClient, ESHOP_BASE_URL
from integrator.models import ProductSyncState
from integrator.sync import SyncOrchestrator


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


def _make_orchestrator(erp_data):
    source = MagicMock()
    source.load.return_value = erp_data
    client = EshopClient()
    return SyncOrchestrator(source=source, client=client)


class TestDeltaSync(TestCase):
    @responses.activate
    def test_first_sync_creates_all(self):
        responses.add(
            responses.POST,
            f"{ESHOP_BASE_URL}/products/",
            json={"status": "created"},
            status=201,
        )

        orchestrator = _make_orchestrator(_erp_data())
        with patch('integrator.sync.time.sleep'):
            result = orchestrator.run()

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

        orchestrator = _make_orchestrator(_erp_data())
        with patch('integrator.sync.time.sleep'):
            orchestrator.run()
            result = orchestrator.run()

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
        orchestrator = _make_orchestrator(erp_data)
        with patch('integrator.sync.time.sleep'):
            orchestrator.run()

        modified_data = [p.copy() for p in erp_data]
        modified_data[0] = {**modified_data[0], "price_vat_excl": 13000.0}

        responses.add(
            responses.POST,
            f"{ESHOP_BASE_URL}/products/",
            json={"status": "created"},
            status=201,
        )

        orchestrator = _make_orchestrator(modified_data)
        with patch('integrator.sync.time.sleep'):
            result = orchestrator.run()

        self.assertEqual(result['synced'], 1)
        self.assertEqual(result['skipped_unchanged'], 3)


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

        orchestrator = _make_orchestrator(erp_data)
        with patch('integrator.sync.time.sleep'):
            result = orchestrator.run()

        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['synced'], 0)
