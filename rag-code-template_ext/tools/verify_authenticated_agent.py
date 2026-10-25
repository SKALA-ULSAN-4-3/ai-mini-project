"""임시 Java/PostgreSQL과 실제 Bearer 인증으로 채점 API를 검증한다.

문서 추출은 저장된 평가 채점표/합성 fixture를 공급한다. 전체 RAG 서버·브라우저 E2E가 아니다.
--disposable-backend는 테스트 회원을 생성해도 되는 임시 백엔드에서만 지정한다.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project-root', type=Path, required=True)
parser.add_argument('--backend-url', required=True)
parser.add_argument('--disposable-backend', action='store_true', required=True)
parser.add_argument('--live-model', action='store_true')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
backend = args.backend_url.rstrip('/')
if urlparse(backend).hostname not in {'localhost', '127.0.0.1', '::1'}:
    parser.error('임시 로컬 백엔드만 허용합니다.')
root = args.project_root.resolve()
sys.path[:0] = [str(root), str(root/'rag-code-template_ext')]
from project_env import load_env
load_env(root/'.env')
os.environ['BACKEND_URL'] = backend
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from backend_auth import get_authenticated_profile
from bid_logic.agent_config import configured_agent_model
from bid_logic.api import create_bid_router
from bid_logic.evaluate import load_cases, scoring_table
from bid_logic.scoring import calculate_scores

report = {'checked_at': datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
          'real_java_backend': True, 'real_postgresql': True,
          'actual_llm_called': args.live_model, 'rag_http_transport': 'uvicorn_loopback',
          'document_extraction': 'cached real evaluation tables + synthetic fixture',
          'checks': [], 'agent_cases': [], 'real_score_items_checked': 0,
          'browser_e2e': False, 'passed': False}
server = None
worker = None

def record(name, condition, **details):
    report['checks'].append({'name': name, 'passed': bool(condition), **details})
    if not condition:
        raise AssertionError(name)

def signatures(items):
    return {i['id']: (i['status'], i.get('expected')) for i in items}

async def scripted_model(messages, specs):
    if any(m['role']=='tool' for m in messages):
        return {'content': '', 'tool_calls': []}
    return {'tool_calls': [{'id': i['id'], 'name': 'calc_score', 'arguments': {'item_id': i['id']}}
                           for i in synthetic['items']]}

try:
    fixtures = load_cases()
    synthetic = scoring_table(fixtures['scoring_templates'][0])
    dataset = root/'rag-code-template_ext/evaluation/real'
    tables = json.loads((dataset/'scoring_tables.json').read_text())
    indexed = {(t['bid_no'], t['revision']): t for t in [synthetic, *tables]}
    def table_provider(no, rev):
        if no == 'PENDING':
            raise HTTPException(409, '제안요청서 준비 중')
        return deepcopy(indexed.get((no, rev)))
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5174'],
        allow_methods=['*'], allow_headers=['*'])
    model = configured_agent_model() if args.live_model else scripted_model
    record('agent_enabled', model is not None)
    app.include_router(create_bid_router(profile_dependency=get_authenticated_profile,
        bids_provider=lambda: [], scoring_provider=table_provider,
        checklist_provider=lambda *a: None, search=lambda *a: [], agent_model=model))
    sock = socket.socket(); sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
    worker = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    worker.start()
    for _ in range(100):
        if server.started: break
        time.sleep(.05)
    record('rag_http_started', server.started)
    with httpx.Client(base_url=backend, timeout=15, trust_env=False) as auth, \
         httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=75, trust_env=False) as rag:
        health=auth.get('/api/health/ready')
        record('java_postgres_ready', health.status_code==200, http_status=health.status_code)
        number=str(secrets.randbelow(9_000_000_000)+1_000_000_000)
        password=secrets.token_urlsafe(24)
        signup={'business_registration_number': number, 'password': password,
            'corporate_name': '임시 통합 검증 회사', 'head_office_address': '서울특별시',
            'business_type': '정보통신업', 'business_item': '소프트웨어 개발',
            'unit_taxpayer_applicable': '부'}
        response=auth.post('/api/signup', json=signup)
        record('signup', response.status_code==201, http_status=response.status_code)
        response=auth.post('/api/login', json={'business_registration_number': number, 'password': password})
        record('login', response.status_code==200, http_status=response.status_code)
        token=response.json()['access_token']
        headers={'Authorization': 'Bearer '+token}
        payload={'bid_no': synthetic['bid_no'], 'revision': synthetic['revision']}
        response=rag.post('/agent/score', json=payload, headers={'Origin':'http://localhost:5174'})
        record('missing_token_401', response.status_code==401, http_status=response.status_code)
        record('cors_on_401', response.headers.get('access-control-allow-origin')=='http://localhost:5174')
        response=rag.post('/agent/score', json=payload, headers={'Authorization': 'Bearer '+token+'invalid'})
        record('tampered_token_401', response.status_code==401, http_status=response.status_code)
        response=rag.post('/agent/score', json=payload, headers=headers)
        record('profile_not_created_404', response.status_code==404, http_status=response.status_code)
        profile={k:v for k,v in fixtures['profiles'][0].items() if k!='id'}
        response=auth.put('/api/profile', json=profile, headers=headers)
        record('profile_save', response.status_code==200, http_status=response.status_code)
        saved=auth.get('/api/profile',headers=headers)
        record('profile_read', saved.status_code==200 and saved.json()['region']=='서울특별시')
        response=rag.post('/agent/score',json={'bid_no':'PENDING','revision':'000'},headers=headers)
        record('rfp_pending_409',response.status_code==409,http_status=response.status_code)
        response=rag.post('/agent/score',json={'bid_no':'UNKNOWN','revision':'000'},headers=headers)
        record('unknown_bid_404',response.status_code==404,http_status=response.status_code)
        response=rag.post('/agent/score',json={'bid_no':synthetic['bid_no']},headers=headers)
        record('missing_revision_422',response.status_code==422,http_status=response.status_code)

        # 실제 프로필 API에 저장한 값이 공급 경계를 통해 다시 채점에 반영되는지 검사한다.
        for name in ('complete', 'needs_input', 'complete_after_profile_update'):
            profile['credit_rating']=None if name=='needs_input' else fixtures['profiles'][0]['credit_rating']
            response=auth.put('/api/profile',json=profile,headers=headers)
            record(name+'_profile_saved',response.status_code==200)
            fixed=rag.get(f"/bids/{payload['bid_no']}/score",params={'revision':payload['revision']},headers=headers)
            record(name+'_fixed_score',fixed.status_code==200)
            response=rag.post('/agent/score',json=payload,headers=headers)
            record(name+'_agent_http',response.status_code==200,http_status=response.status_code)
            result=response.json()
            expected='needs_input' if name=='needs_input' else 'complete'
            record(name+'_status',result['status']==expected,status=result['status'])
            record(name+'_matches_fixed',signatures(result['items'])==signatures(fixed.json()['items']))
            if name=='needs_input':
                record('missing_credit_question', 'credit_rating' in result['missing_fields'] and bool(result['questions']))
            report['agent_cases'].append({'case':name,'status':result['status'],
                'latency_ms':result['latency_ms'],'model_calls':result['model_calls'],
                'missing_fields':result['missing_fields'],'questions':result['questions'],
                'token_usage':result['token_usage']})

        profiles=json.loads((dataset/'profiles.json').read_text())
        for p in profiles:
            response=auth.put('/api/profile',json=p,headers=headers)
            record('real_profile_'+p['id'],response.status_code==200)
            for table in tables:
                response=rag.get(f"/bids/{table['bid_no']}/score",params={'revision':table['revision']},headers=headers)
                record('real_score_'+p['id']+'_'+table['bid_no'],response.status_code==200)
                result=response.json()
                expected=calculate_scores(table,p,table['bid_no'],table['revision'])
                record('real_score_match_'+p['id']+'_'+table['bid_no'],signatures(result['items'])==signatures(expected['items']))
                report['real_score_items_checked']+=len(result['items'])
        report['passed']=True
except Exception as exc:
    report['error_type']=type(exc).__name__
finally:
    if server is not None:
        server.should_exit=True
    if worker is not None:
        worker.join(timeout=5)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),
                      'agent_cases':report['agent_cases'],
                      'real_score_items_checked':report['real_score_items_checked'],
                      'error_type':report.get('error_type')},ensure_ascii=False,indent=2))
    if not report['passed']:sys.exit(1)
