"""기존 Java 문서 API를 통한 원본·변환본·전처리 상태의 영속 저장과 복원.

파일 본문은 Storage, 메타데이터는 기존 bid_documents 테이블에 보관한다.
내부 상태는 예약 파일명으로 구분하고 서비스 키 조회에서만 노출한다.
"""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from .common import read_json, read_jsonl, write_json, write_jsonl

MAX_BYTES = 50 * 1024 * 1024


def identity(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]


class BackendStore:
    def __init__(self, bid_no, revision):
        self.bid_no, self.revision = str(bid_no), str(revision)
        self.base = os.environ.get('BACKEND_URL', '').strip().rstrip('/')
        self.key = os.environ.get('SERVICE_API_KEY', '').strip()
        self.configured = bool(self.base and self.key)
        self.documents = None
        self.download_urls_loaded = False
        self.blocked = False
        self.auth_failed = False
        self.errors, self.saved, self.reused = [], 0, 0
        self.files = []
        self.client = httpx.Client(timeout=20, follow_redirects=False) if self.configured else None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.client:
            self.client.close()

    def _error(self, step, status=None, *, service_auth=True):
        if status in (401, 403, 500, 502, 503, 504):
            self.blocked = True
        if status in (401, 403, 503) and service_auth:
            self.auth_failed = True
            step = 'DB 인증 실패 — 파이프라인 SERVICE_API_KEY와 Java SERVICE_API_KEY 설정을 확인하세요'
        message = step + (f' (HTTP {status})' if status else '')
        if message not in self.errors:
            self.errors.append(message)

    @property
    def report(self):
        return {'status': 'not_configured' if not self.configured else 'failed' if self.errors else 'saved' if self.saved or self.reused else 'not_needed',
                'auth_failed': self.auth_failed,
                'saved': self.saved, 'reused': self.reused, 'errors': list(self.errors), 'files': list(self.files)}

    def list(self):
        if not self.configured:
            return []
        if self.documents is None:
            try:
                response = self.client.get(self.base + '/api/bids/' + quote(self.bid_no, safe='') + '/documents',
                    params={'revision': self.revision, 'download_urls': 'false'}, headers={'X-Service-Key': self.key})
                if response.status_code != 200:
                    self._error('DB 문서 목록 조회 실패', response.status_code)
                    self.documents = []
                    return []
                data = response.json()
                if not isinstance(data, list):
                    raise ValueError('invalid list')
                self.documents = data
            except (httpx.HTTPError, ValueError):
                self.blocked = True
                self._error('DB 문서 목록 연결 실패')
                self.documents = []
                return []
        return self.documents

    def find(self, kind, key):
        prefix = f'dp1_{kind}_{key}_'
        return next((row for row in reversed(self.list())
                     if str(row.get('file_name', '')).startswith(prefix)), None)

    def read(self, row):
        if not row or not self.configured:
            return None
        url = row.get('download_url')
        if not url and not self.download_urls_loaded and not self.blocked:
            # 여러 파일을 복원해도 서명 URL 발급은 공고별 한 번만 요청한다.
            self.download_urls_loaded = True
            try:
                response = self.client.get(self.base + '/api/bids/' + quote(self.bid_no, safe='') + '/documents',
                    params={'revision': self.revision, 'download_urls': 'true'},
                    headers={'X-Service-Key': self.key})
                if response.status_code == 200:
                    entries = response.json()
                    if not isinstance(entries, list):
                        raise ValueError('invalid document list')
                    by_name = {entry['file_name']: entry for entry in entries}
                    for document in self.list():
                        document.update(by_name.get(document.get('file_name'), {}))
                    row.update(by_name.get(row.get('file_name'), {}))
                    url = row.get('download_url')
                else:
                    self._error('DB 다운로드 주소 발급 실패', response.status_code)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                self._error('DB 다운로드 주소 발급 연결 실패')
        if self.blocked:
            return None
        if not url:
            try:
                response = self.client.get(self.base + '/api/bids/' + quote(self.bid_no, safe='') + '/documents',
                    params={'revision': self.revision, 'file_name': row['file_name']},
                    headers={'X-Service-Key': self.key})
                if response.status_code != 200:
                    self._error('DB 다운로드 주소 발급 실패', response.status_code)
                    return None
                entries = response.json()
                url = entries[0].get('download_url') if entries else None
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                self._error('DB 다운로드 주소 발급 연결 실패')
                return None
        if not url:
            self._error('DB 다운로드 주소 없음')
            return None
        parsed = urlparse(url)
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1')):
            self._error('DB 다운로드 주소 확인 실패')
            return None
        try:
            # 서비스 키는 Java 요청에만 보낸다. Storage 서명 주소에는 전달하지 않는다.
            with self.client.stream('GET', url) as response:
                if response.status_code != 200:
                    self._error('DB 파일 복원 실패', response.status_code, service_auth=False)
                    return None
                chunks, total = [], 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ValueError('oversized')
                    chunks.append(chunk)
            data = b''.join(chunks)
            parts = str(row.get('file_name', '')).split('_', 4)
            if len(parts) == 5 and parts[0] == 'dp1' and hashlib.sha256(data).hexdigest() != parts[3]:
                raise ValueError('hash mismatch')
            return data
        except (httpx.HTTPError, ValueError):
            self._error('DB 파일 복원·해시 검증 실패')
            return None

    def _failed_file(self, kind, name):
        if kind != 'state':
            self.files.append({'file_name': name, 'kind': kind, 'status': 'failed'})
        return False

    def put(self, kind, key, name, data, source_url=''):
        if not self.configured:
            return False
        if self.blocked:
            return self._failed_file(kind, name)
        digest = hashlib.sha256(data).hexdigest()
        suffix = Path(name).suffix[:10]
        logical_name = Path(name).stem[:250 - len(suffix)] + suffix
        filename = f'dp1_{kind}_{key}_{digest}_{logical_name}'
        documents = self.list()
        # 목록 조회에서 인증 실패가 확인되면 POST로 같은 잘못된 키를 재전송하지 않는다.
        if self.blocked:
            return self._failed_file(kind, name)
        if any(row.get('file_name') == filename for row in documents):
            self.reused += 1
            if kind != 'state': self.files.append({'file_name': name, 'kind': kind, 'status': 'reused'})
            return True
        if not data or len(data) > MAX_BYTES:
            self._error('DB 저장 파일 크기 확인 실패')
            return self._failed_file(kind, name)
        try:
            response = self.client.post(self.base + '/api/bids/' + quote(self.bid_no, safe='') + '/documents',
                params={'revision': self.revision, 'file_name': filename, 'source_url': source_url},
                headers={'X-Service-Key': self.key, 'Content-Type': 'application/octet-stream'}, content=data)
            if response.status_code == 409:
                self.documents = None
                if any(row.get('file_name') == filename for row in self.list()):
                    self.reused += 1
                    if kind != 'state': self.files.append({'file_name': name, 'kind': kind, 'status': 'reused'})
                    return True
            if response.status_code != 201:
                self._error('DB 파일 저장 실패', response.status_code)
                return self._failed_file(kind, name)
            row = response.json()
            if self.documents is None:
                self.documents = []
            self.documents.append(row)
            self.saved += 1
            if kind != 'state': self.files.append({'file_name': name, 'kind': kind, 'status': 'saved'})
            return True
        except (httpx.HTTPError, ValueError):
            self.blocked = True
            self._error('DB 파일 저장 연결 실패')
            return self._failed_file(kind, name)

    def put_file(self, kind, key, name, path, source_url='', digest=None):
        """저장된 해시를 먼저 비교해 재사용 파일의 본문을 다시 메모리에 읽지 않는다."""
        if not self.configured:
            return False
        if self.blocked:
            return self._failed_file(kind, name)
        path = Path(path)
        size = path.stat().st_size
        if not size or size > MAX_BYTES:
            self._error('DB 저장 파일 크기 확인 실패')
            return self._failed_file(kind, name)
        if digest is None:
            hasher = hashlib.sha256()
            with path.open('rb') as source:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    hasher.update(block)
            digest = hasher.hexdigest()
        row = self.find(kind, key)
        if row and str(row.get('file_name', '')).startswith(f'dp1_{kind}_{key}_{digest}_'):
            self.reused += 1
            if kind != 'state':
                self.files.append({'file_name': name, 'kind': kind, 'status': 'reused'})
            return True
        return self.put(kind, key, name, path.read_bytes(), source_url)

    def restore(self, kind, key, target, legacy_name='', source_url=''):
        row = self.find(kind, key)
        if row is None and kind == 'original' and legacy_name.lower().endswith('.pdf'):
            row = next((r for r in reversed(self.list())
                        if r.get('file_name') == legacy_name and r.get('source_url') == source_url), None)
        data = self.read(row)
        if data is None:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + '.dbpart')
        temporary.write_bytes(data)
        temporary.replace(target)
        self.reused += 1
        return True

    def restore_prepared(self, folder, fingerprint, rows):
        payload = self.read(self.find('state', fingerprint[:24]))
        if payload is None:
            return False
        try:
            state = json.loads(payload)
            if state.get('format') != 1 or state.get('fingerprint') != fingerprint:
                return False
            paths = {row['url']: row['local_path'] for row in rows if row.get('local_path')}
            original_paths = dict(paths)
            documents = state.get('documents', [])
            if (not documents or {d.get('source_url') for d in documents} != set(paths)
                    or any(d.get('status') not in ('extracted', 'review_empty_pages') for d in documents)):
                return False
            conversions = folder / 'conversions.jsonl'
            if conversions.is_file():
                for entry in read_jsonl(conversions):
                    for url, path in original_paths.items():
                        pdf = Path(entry.get('pdf_path') or '')
                        if (entry.get('original_path') == path and entry.get('status') in ('converted', 'existing')
                                and pdf.is_file() and entry.get('pdf_sha256') == hashlib.sha256(pdf.read_bytes()).hexdigest()):
                            paths[url] = str(pdf)
            if any(Path(path).suffix.lower() in ('.hwp', '.hwpx') and paths[url] == path
                   for url, path in original_paths.items()):
                return False
            output = folder / 'processed'
            output.mkdir(exist_ok=True)
            outputs = {}
            for name in ('pages', 'chunks', 'documents', 'needs_attention'):
                records = state.get(name, [])
                for record in records:
                    url = record.get('source_url')
                    if url not in paths:
                        raise ValueError('unknown document')
                    record['local_path'] = paths[url]
                    record['original_local_path'] = original_paths[url]
                target = output / (name + '.jsonl')
                write_jsonl(target, records)
                outputs[str(target.relative_to(folder))] = hashlib.sha256(target.read_bytes()).hexdigest()
            write_json(folder / 'prepared-cache.json', {'fingerprint': fingerprint, 'outputs': outputs})
            self.reused += 1
            return True
        except (ValueError, TypeError, KeyError, OSError):
            self._error('DB 전처리 상태 복원 실패')
            return False

    def save_prepared(self, folder):
        cache = folder / 'prepared-cache.json'
        if not self.configured or not cache.is_file() or self.errors:
            return
        fingerprint = read_json(cache)['fingerprint']
        if self.find('state', fingerprint[:24]):
            self.reused += 1
            return
        state = {'format': 1, 'fingerprint': fingerprint}
        for name in ('pages', 'chunks', 'documents', 'needs_attention'):
            path = folder / 'processed' / (name + '.jsonl')
            records = read_jsonl(path) if path.is_file() else []
            state[name] = [{k: v for k, v in row.items()
                            if k not in ('local_path', 'original_local_path')} for row in records]
        self.put('state', fingerprint[:24], 'prepared.json', json.dumps(state, ensure_ascii=False).encode())


def summary_with_database(bid_no, revision, authorization, fingerprint, generator_version, build, refresh=False):
    """기업별 요약을 DB에서 먼저 읽고, 문서·생성 버전이 다를 때만 새로 만든다."""
    base = os.environ.get('BACKEND_URL', '').strip().rstrip('/')
    if not base or not authorization:
        return {**build(), 'db_persistence': {'status': 'not_configured'}}
    endpoint = base + '/api/bids/' + quote(bid_no, safe='') + '/summary'
    metadata = {'schema': 1, 'document_fingerprint': fingerprint, 'generator_version': generator_version}
    failure = None
    with httpx.Client(timeout=httpx.Timeout(8, connect=3), follow_redirects=False) as client:
        headers = {'Authorization': authorization}
        if not refresh and fingerprint is not None:
            try:
                response = client.get(endpoint, params={'revision': revision, 'include_documents': 'false'}, headers=headers)
                if response.status_code == 200:
                    saved = response.json()
                    if (saved.get('bid_no') == bid_no and saved.get('revision') == revision
                            and isinstance(saved.get('summary'), dict)
                            and saved['summary'].get('_pipeline_cache') == metadata):
                        return {k: saved.get(k) for k in ('bid_no', 'revision', 'summary', 'missing', 'needs_review', 'handoff')} | {
                            'latency_ms': 0, 'db_persistence': {'status': 'reused'}}
                elif response.status_code != 404:
                    failure = f'DB 요약 조회 실패 (HTTP {response.status_code})'
            except (httpx.HTTPError, ValueError, TypeError):
                failure = 'DB 요약 조회 연결 실패'
        result = build()
        result = {**result, 'summary': {**result['summary'], '_pipeline_cache': metadata}}
        if failure is None:
            payload = {k: result.get(k) for k in ('revision', 'summary', 'missing', 'needs_review', 'handoff', 'latency_ms')}
            try:
                response = client.put(endpoint, json=payload, headers=headers)
                if response.status_code == 200:
                    return {**result, 'db_persistence': {'status': 'saved'}}
                failure = f'DB 요약 저장 실패 (HTTP {response.status_code})'
            except httpx.HTTPError:
                failure = 'DB 요약 저장 연결 실패'
        return {**result, 'db_persistence': {'status': 'failed', 'error': failure}}
