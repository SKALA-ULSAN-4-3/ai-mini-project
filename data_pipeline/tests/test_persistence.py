import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from data_pipeline import persistence


class PersistenceTests(unittest.TestCase):
    def test_bulk_download_urls_and_file_reuse_do_not_repeat_java_requests(self):
        contents = {'a': b'first', 'b': b'second'}
        names = {key: f'dp1_original_{key}_{hashlib.sha256(data).hexdigest()}_{key}.pdf'
                 for key, data in contents.items()}
        java_requests = []
        def handler(request):
            if request.url.host == 'storage.test':
                return httpx.Response(200, content=contents[request.url.path.strip('/')])
            self.assertEqual(request.method, 'GET')
            java_requests.append(dict(request.url.params))
            signed = request.url.params.get('download_urls') == 'true'
            return httpx.Response(200, json=[{'file_name': names[key],
                **({'download_url': 'https://storage.test/' + key} if signed else {})} for key in names])
        real_client = httpx.Client
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,
                {'BACKEND_URL': 'https://java.test', 'SERVICE_API_KEY': 'test'}), patch.object(
                persistence.httpx, 'Client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler))):
            with persistence.BackendStore('B1', '000') as store:
                for key, data in contents.items():
                    target = Path(temp) / (key + '.pdf')
                    self.assertTrue(store.restore('original', key, target))
                    with patch.object(Path, 'read_bytes', side_effect=AssertionError('duplicate body read')):
                        self.assertTrue(store.put_file('original', key, target.name, target))
                self.assertEqual(len(java_requests), 2)
                self.assertEqual([q['download_urls'] for q in java_requests], ['false', 'true'])

    def test_original_round_trip_checks_content_hash_and_reuses_existing(self):
        stored = {}
        content = b"original PDF bytes"

        def handler(request):
            if request.method == "GET" and request.url.path.endswith("/documents"):
                rows = [{"file_name": name, "download_url": "https://storage.test/file"}
                        for name in stored]
                return httpx.Response(200, json=rows)
            if request.method == "GET" and request.url.host == "storage.test":
                return httpx.Response(200, content=stored[next(iter(stored))])
            if request.method == "POST":
                name = request.url.params["file_name"]
                stored[name] = request.content
                return httpx.Response(201, json={"file_name": name})
            raise AssertionError(f"unexpected request {request.method} {request.url}")

        env = {"BACKEND_URL": "https://java.test", "SERVICE_API_KEY": "test"}
        real_client = httpx.Client
        with patch.dict(os.environ, env), patch.object(
                persistence.httpx, "Client",
                side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler))):
            with persistence.BackendStore("BID-1", "000") as store:
                self.assertTrue(store.put("original", "a" * 24, "source.pdf", content))
                self.assertTrue(store.put("original", "a" * 24, "source.pdf", content))
                self.assertEqual(store.saved, 1)
                self.assertEqual(store.reused, 1)
                row = store.find("original", "a" * 24)
                target = Path("/tmp/persistence-roundtrip.pdf")
                try:
                    self.assertTrue(store.restore("original", "a" * 24, target))
                    self.assertEqual(hashlib.sha256(target.read_bytes()).digest(),
                                     hashlib.sha256(content).digest())
                finally:
                    target.unlink(missing_ok=True)
                # Corrupted storage bytes are rejected against the digest in the object name.
                stored[row["file_name"]] = b"corrupt"
                store.documents = None
                self.assertIsNone(store.read(store.find("original", "a" * 24)))

    def test_summary_reuses_matching_metadata_and_regenerates_when_changed(self):
        saved = {}
        requests = []

        def handler(request):
            requests.append(request.method)
            if request.method == "GET":
                return httpx.Response(200, json=saved) if saved else httpx.Response(404)
            saved.update(json.loads(request.content))
            saved.update({"bid_no": "BID-1", "revision": "000"})
            return httpx.Response(200, json=saved)

        build_count = []

        def build():
            build_count.append(1)
            return {"bid_no": "BID-1", "revision": "000", "summary": {"text": "summary"},
                    "missing": [], "needs_review": [], "handoff": {}, "latency_ms": 12}

        real_client = httpx.Client
        with patch.dict(os.environ, {"BACKEND_URL": "https://java.test"}), patch.object(
                persistence.httpx, "Client",
                side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler))):
            first = persistence.summary_with_database("BID-1", "000", "Bearer user", "fp1", "v1", build)
            second = persistence.summary_with_database("BID-1", "000", "Bearer user", "fp1", "v1", build)
            third = persistence.summary_with_database("BID-1", "000", "Bearer user", "fp2", "v1", build)
        self.assertEqual(len(build_count), 2)
        self.assertEqual(first["db_persistence"]["status"], "saved")
        self.assertEqual(second["db_persistence"]["status"], "reused")
        self.assertEqual(third["db_persistence"]["status"], "saved")
        self.assertEqual(requests, ["GET", "PUT", "GET", "GET", "PUT"])


if __name__ == "__main__":
    unittest.main()
