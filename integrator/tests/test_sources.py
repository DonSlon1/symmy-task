import json
import os
import tempfile

from django.test import TestCase

from integrator.sources.json_source import JsonFileSource


class TestLoadErpData(TestCase):
    def test_loads_json_from_file(self):
        data = [{"id": "SKU-TEST", "title": "Test"}]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
            tmp_path = f.name
        try:
            result = JsonFileSource(path=tmp_path).load()
            self.assertEqual(result, data)
        finally:
            os.unlink(tmp_path)

    def test_loads_default_erp_file(self):
        result = JsonFileSource().load()
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)
