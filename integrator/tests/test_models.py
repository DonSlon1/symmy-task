from django.test import TestCase

from integrator.models import ProductSyncState


class TestProductSyncStateModel(TestCase):
    def test_str(self):
        state = ProductSyncState.objects.create(sku="SKU-TEST", data_hash="abc123")
        self.assertIn("SKU-TEST", str(state))
