import responses
from unittest.mock import patch

from django.test import TestCase

from integrator.clients.eshop_client import EshopClient, ESHOP_BASE_URL


class TestApiCommunication(TestCase):
    def setUp(self):
        self.client = EshopClient()
        self.session = self.client.make_session()

    @responses.activate
    def test_post_new_product(self):
        responses.add(
            responses.POST,
            f"{ESHOP_BASE_URL}/products/",
            json={"status": "created"},
            status=201,
        )

        payload = {"sku": "SKU-001", "title": "Test", "price": 100, "stock": 1, "color": "N/A"}
        resp = self.client.send(self.session, payload, is_update=False)

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

        payload = {"sku": "SKU-001", "title": "Test", "price": 100, "stock": 1, "color": "N/A"}
        resp = self.client.send(self.session, payload, is_update=True)

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

        payload = {"sku": "SKU-001", "title": "Test", "price": 100, "stock": 1, "color": "N/A"}

        with patch('integrator.clients.eshop_client.RETRY_BASE_DELAY', 0.01):
            resp = self.client.send(self.session, payload, is_update=False)

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

        payload = {"sku": "SKU-001", "title": "Test", "price": 100, "stock": 1, "color": "N/A"}

        with patch('integrator.clients.eshop_client.RETRY_BASE_DELAY', 0.01):
            with self.assertRaisesRegex(Exception, "Rate limit exceeded"):
                self.client.send(self.session, payload, is_update=False)
