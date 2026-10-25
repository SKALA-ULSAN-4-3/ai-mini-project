"""공식 평가 원문을 공개 URL로 복원하고 해시를 확인한다. 정답은 변경하지 않는다."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
DATASET = Path(__file__).resolve().parents[1] / 'evaluation/real'
ASSETS = ROOT / 'data/evaluation-source-20261023'


def source_path(assets, row):
    for field in ('bid_no', 'bid_order', 'file_name'):
        value = row[field]
        if not value or value in {'.', '..'} or '/' in value or '\\' in value:
            raise ValueError('원문 경로에 잘못된 이름이 있습니다.')
    return assets / 'raw' / f"{row['bid_no']}_{row['bid_order']}" / row['file_name']


def verify(data, row):
    if hashlib.sha256(data).hexdigest() != row['sha256']:
        raise ValueError(f"원문 SHA-256 불일치: {row['bid_no']} / {row['file_name']}")
    if row['file_name'].lower().endswith('.pdf') and not data.startswith(b'%PDF-'):
        raise ValueError('PDF 대신 오류 페이지가 반환됐습니다.')


def restore(dataset=DATASET, assets=ASSETS, offline=False):
    rows = json.loads((dataset / 'source-manifest.json').read_text())
    attachments = []
    for row in rows:
        target = source_path(assets, row)
        if target.exists():
            verify(target.read_bytes(), row)
        else:
            if offline:
                raise FileNotFoundError(target)
            url = urlparse(row['url'])
            if url.scheme != 'https' or url.hostname != 'www.g2b.go.kr':
                raise ValueError('나라장터 HTTPS 원문 URL만 허용합니다.')
            request = Request(row['url'], headers={'User-Agent': 'Mozilla/5.0'})
            for attempt in range(3):
                try:
                    with urlopen(request, timeout=45) as response:
                        data = response.read(100 * 1024 * 1024 + 1)
                    verify(data, row)
                    break
                except (URLError, TimeoutError, ValueError):
                    if attempt == 2:
                        raise
                    time.sleep(attempt + 1)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        attachments.append({**row, 'local_path': str(target.resolve())})
        print(f"verified {len(attachments)}/{len(rows)}", flush=True)
    from pypdf import PdfReader
    sys.path.insert(0, str(ROOT))
    from data_pipeline.privacy import mask_personal
    blocks = []
    for row in attachments:
        if not row['file_name'].lower().endswith('.pdf'):
            continue
        for page, content in enumerate(PdfReader(row['local_path']).pages, 1):
            blocks.append({'id': len(blocks) + 1, 'source': {
                'bid_no': row['bid_no'], 'revision': row['bid_order'],
                'filename': row['file_name'], 'page': page,
                'url': row['url'], 'sha256': row['sha256']},
                'text': mask_personal(content.extract_text() or '')})
    if len({b['source']['bid_no'] for b in blocks if '제안요청서' not in b['source']['filename']}) != 20:
        raise ValueError('고정 공고 20건의 PDF 근거가 모두 필요합니다.')
    assets.mkdir(parents=True, exist_ok=True)
    for name, data in (('attachments.json', attachments), ('evidence.json', blocks)):
        if name == 'evidence.json' and (assets / name).exists():
            print('Existing evidence preserved: original IDs and HWPX blocks.')
            continue
        (assets / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print(f'Restored {len(rows)} files / {len(blocks)} PDF pages. Gold unchanged.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    restore(offline=args.offline)
