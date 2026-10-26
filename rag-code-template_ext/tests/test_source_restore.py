import hashlib
from pathlib import Path
import unittest
from bid_logic.restore_sources import source_path, verify

class SourceRestoreTest(unittest.TestCase):
    def test_corrupt_source_and_unsafe_path_rejected(self):
        data = b'%PDF-1.7 fixture'
        row = {'bid_no': 'B', 'bid_order': '000', 'file_name': 'a.pdf',
               'sha256': hashlib.sha256(data).hexdigest()}
        verify(data, row)
        with self.assertRaises(ValueError): verify(b'changed', row)
        for field in ('bid_no', 'bid_order', 'file_name'):
            with self.assertRaises(ValueError): source_path(Path('assets'), {**row, field: '../escape'})
