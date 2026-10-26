"""운영 API 점검. 비밀번호·토큰·공고 본문은 보고서에 저장하지 않는다."""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path

import httpx


def _verify(args):
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "rag_url": args.rag_url,
              "backend_url": args.backend_url, "origin": args.origin, "checks": []}
    checks = report['checks']
    with httpx.Client(timeout=90, follow_redirects=False) as client:
        def record(name, response, expected, **details):
            row = {"name": name, "status": response.status_code,
                   "passed": response.status_code == expected, **details}
            checks.append(row)
            return row
        response = client.get(args.rag_url + '/health')
        record('health', response, 200)
        response = client.get(args.rag_url + '/openapi.json')
        row = record('routes', response, 200)
        required = {'/search-bids', '/fetch-notices', '/fetch-documents', '/retry-db-save', '/jobs/{job_id}', '/bids', '/rag-query'}
        paths = response.json().get('paths', {}) if row['passed'] else {}
        row['missing_routes'] = sorted(required - paths.keys())
        row['passed'] &= not row['missing_routes']
        headers = {'Origin': args.origin}
        for name, method, path in [('unauthenticated_bids', 'GET', '/bids'),
                                   ('unauthenticated_search', 'POST', '/search-bids')]:
            response = client.request(method, args.rag_url + path, headers=headers)
            cors = response.headers.get('access-control-allow-origin')
            row = record(name, response, 401, cors_origin=cors)
            row['passed'] &= cors in ('*', args.origin)
        response = client.get(args.backend_url + '/api/auth/check', headers=headers)
        record('backend_reachable_unauthenticated', response, 401)
        response = client.options(args.backend_url + '/api/login', headers={
            **headers, 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type'})
        cors = response.headers.get('access-control-allow-origin')
        row = record('backend_login_preflight', response, 204, cors_origin=cors)
        row['passed'] &= (cors in ('*', args.origin)
                          and 'POST' in response.headers.get('access-control-allow-methods', '').upper()
                          and any(h in response.headers.get('access-control-allow-headers', '').lower()
                                  for h in ('content-type', '*')))
        token = os.environ.get('MINI_TEST_TOKEN', '').strip()
        if not token and os.environ.get('MINI_TEST_BUSINESS_NUMBER') and os.environ.get('MINI_TEST_PASSWORD'):
            response = client.post(args.backend_url + '/api/login', json={
                'business_registration_number': os.environ['MINI_TEST_BUSINESS_NUMBER'],
                'password': os.environ['MINI_TEST_PASSWORD']})
            record('login', response, 200)
            if response.status_code == 200:
                token = response.json().get('access_token')
                if not isinstance(token, str) or not token.strip():
                    row = checks[-1]
                    row.update(passed=False, error='missing_access_token')
                    token = ''
        if token:
            headers['Authorization'] = 'Bearer ' + token
            response = client.get(args.backend_url + '/api/profile', headers=headers)
            row = record('profile', response, 200)
            row['passed'] &= response.status_code == 200 and isinstance(response.json(), dict) and bool(response.json())
            if row['passed']:
                response = client.post(args.rag_url + '/search-bids', headers=headers,
                                       json={'from': args.start, 'to': args.end, 'queries': args.query, 'limit': 100})
                row = record('search_bids', response, 200)
                if response.status_code == 200:
                    data = response.json()
                    search_id = data.get('search_id')
                    deadline_start = data.get('deadline_from') or args.start
                    deadline_end = data.get('deadline_to') or args.end
                    row.update(search_id=search_id, items=len(data.get('items', [])))
                    row['passed'] &= bool(search_id) and bool(data.get('items'))
                    if search_id:
                        response = client.get(args.rag_url + '/bids', headers=headers,
                                              params={'from': deadline_start, 'to': deadline_end, 'search_id': search_id, 'limit': 20})
                        row = record('bids', response, 200)
                        if response.status_code == 200:
                            data = response.json()
                            row.update(bids=len(data.get('bids', [])), excluded=len(data.get('excluded', [])),
                                       candidate_count=data.get('candidate_count'))
                            row['passed'] &= bool(data.get('bids'))
        else:
            checks.append({'name': 'authenticated_search_to_bids', 'passed': False,
                           'status': 'pending_credentials'})
    core = {'health', 'routes', 'unauthenticated_bids', 'unauthenticated_search', 'profile', 'search_bids', 'bids'}
    status = {row['name']: row['passed'] for row in checks}
    report['data_pipeline_passed'] = all(status.get(name, False) for name in core)
    report['passed'] = all(row['passed'] for row in checks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return not report['passed']


def verify(args):
    try:
        return _verify(args)
    except (httpx.RequestError, ValueError, TypeError, KeyError) as exc:
        # 인증 값·HTTP 오류 원문을 기록하지 않고 실패를 명시한다.
        report = {"checked_at": datetime.now(timezone.utc).isoformat(),
                  "rag_url": args.rag_url, "backend_url": args.backend_url,
                  "origin": args.origin, "passed": False, "data_pipeline_passed": False,
                  "checks": [{"name": "verification_interrupted", "passed": False,
                              "error": type(exc).__name__}]}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1


def main():
    from project_env import load_env
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rag-url', default='https://ai-mini-datapipeline.onrender.com')
    parser.add_argument('--backend-url', default='https://ai-service-mini-backend.onrender.com')
    parser.add_argument('--origin', default='http://localhost:5174')
    parser.add_argument('--from', dest='start', default=str(date.today() - timedelta(days=14)))
    parser.add_argument('--to', dest='end', default=str(date.today()))
    parser.add_argument('--query', action='append', default=None)
    parser.add_argument('--output', type=Path, default=Path('data/render-verification.json'))
    args = parser.parse_args()
    args.query = args.query or ['시스템']
    for url in (args.rag_url, args.backend_url):
        if not url.startswith('https://'):
            parser.error('로그인 토큰 보호를 위해 HTTPS 주소가 필요합니다.')
    return verify(args)


if __name__ == '__main__':
    raise SystemExit(main())
