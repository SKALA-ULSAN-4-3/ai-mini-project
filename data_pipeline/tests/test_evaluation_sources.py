import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from data_pipeline.evaluation_sources import DATASET, collect, official_sources, safe_name
from data_pipeline.collect_bids import CollectionError


class EvaluationSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.dataset = self.base / 'dataset'
        self.dataset.mkdir()
        for name in ('bids.csv', 'manifest.json', 'source-manifest.json'):
            shutil.copyfile(DATASET/name, self.dataset/name)
        self.sources = official_sources(self.dataset)
        self.assets = self.base / 'assets'

    def test_reject_other_revision_before_download(self):
        self.sources[0]['bid_order'] = '999'
        (self.dataset/'source-manifest.json').write_text(json.dumps(self.sources))
        with self.assertRaises(ValueError):
            collect(self.dataset, self.assets)
        self.assertFalse(self.assets.exists())

    def test_reject_url_revision_and_missing_hash(self):
        for field, value in (('url', self.sources[0]['url'].replace('Ord=000','Ord=001')),
                             ('sha256', '')):
            with self.subTest(field=field):
                changed = [dict(a) for a in self.sources]
                changed[0][field] = value
                (self.dataset/'source-manifest.json').write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    official_sources(self.dataset)

    def test_verify_detects_tamper_and_missing_without_network(self):
        row = self.sources[0]
        path = self.assets/'raw'/f"{row['bid_no']}_{row['bid_order']}"/safe_name(row['file_name'])
        path.parent.mkdir(parents=True)
        path.write_bytes(b'tampered')
        with patch('data_pipeline.evaluation_sources.download_file') as download:
            report = collect(self.dataset, self.assets, verify_only=True)
        download.assert_not_called()
        self.assertEqual(len(report['failures']), 74)
        self.assertEqual(report['failures'][0]['error'], 'sha256_mismatch')
        self.assertEqual(report['failures'][1]['error'], 'missing')
        self.assertEqual(path.read_bytes(), b'tampered')

    def test_download_failure_is_recorded_and_valid_file_is_reused(self):
        row = self.sources[0]
        row['sha256'] = hashlib.sha256(b'valid').hexdigest()
        (self.dataset/'source-manifest.json').write_text(json.dumps(self.sources))
        path = self.assets/'raw'/f"{row['bid_no']}_{row['bid_order']}"/safe_name(row['file_name'])
        path.parent.mkdir(parents=True)
        path.write_bytes(b'valid')
        with patch('data_pipeline.evaluation_sources.download_file', side_effect=CollectionError('offline')) as download:
            report = collect(self.dataset, self.assets)
        self.assertEqual(download.call_count, 73)
        self.assertEqual(report['verified_files'], 1)
        self.assertEqual(len(json.loads((self.assets/'download-failures.json').read_text())), 73)
        self.assertFalse((self.assets/'evidence.json').exists())

    def test_invalid_raw_files_remove_stale_success_outputs(self):
        self.assets.mkdir()
        for name in ('attachments.json', 'evidence.json'):
            (self.assets/name).write_text('[{"stale":true}]')
        with patch('data_pipeline.evaluation_sources.download_file') as download:
            report = collect(self.dataset, self.assets, verify_only=True)
        download.assert_not_called()
        self.assertFalse(report['passed'])
        self.assertFalse((self.assets/'evidence.json').exists())
        self.assertFalse((self.assets/'attachments.json').exists())

    def test_extraction_failure_is_recorded_and_invalidates_evidence(self):
        row = dict(self.sources[0], sha256=hashlib.sha256(b'valid').hexdigest())
        target = self.assets/'raw'/f"{row['bid_no']}_{row['bid_order']}"/safe_name(row['file_name'])
        target.parent.mkdir(parents=True)
        target.write_bytes(b'valid')
        (self.assets/'evidence.json').write_text('[{"stale":true}]')
        with patch('data_pipeline.evaluation_sources.official_sources', return_value=[row]), \
             patch('data_pipeline.evaluation_sources.build_evidence', side_effect=ValueError('bad document')), \
             patch('data_pipeline.evaluation_sources.download_file') as download:
            report = collect(self.dataset, self.assets)
        download.assert_not_called()
        self.assertEqual(report['verified_files'], 1)
        self.assertFalse(report['passed'])
        self.assertEqual(report['failures'], [{'stage': 'evidence', 'error': 'ValueError'}])
        self.assertFalse((self.assets/'evidence.json').exists())
        self.assertEqual(json.loads((self.assets/'verification.json').read_text())['passed'], False)

    def test_invalid_manifest_removes_stale_evidence_before_aborting(self):
        self.assets.mkdir()
        (self.assets/'evidence.json').write_text('[{"stale":true}]')
        self.sources[0]['bid_order'] = '999'
        (self.dataset/'source-manifest.json').write_text(json.dumps(self.sources))
        with self.assertRaises(ValueError):
            collect(self.dataset, self.assets)
        self.assertFalse((self.assets/'evidence.json').exists())


if __name__ == '__main__':
    unittest.main()
