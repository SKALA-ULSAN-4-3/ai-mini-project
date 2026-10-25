import ast
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace as NS
import json
import unittest
from unittest.mock import patch
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from bid_logic.agent_config import configured_agent_model
from bid_logic.api import create_bid_router
from bid_logic.evaluate import load_cases, scoring_table


class AgentConfigTest(unittest.TestCase):
    def test_configuration_and_actual_startup(self):
        self.assertIsNone(configured_agent_model({'BID_AGENT_ENABLED': 'false'}))
        for env in ({}, {'BID_AGENT_ENABLED': 'bad'}, {'OPENAI_API_KEY': 'fixture', 'BID_AGENT_MODEL': ''}):
            with self.assertRaises(ValueError):
                configured_agent_model(env)
        path = Path(__file__).resolve().parents[1] / 'rag_external-web_pdf_closed_llm.py'
        node = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.If)
                    and ast.unparse(n.test) == 'backend_url()')
        calls = []
        model = configured_agent_model({'OPENAI_API_KEY': 'fixture'})
        namespace = dict(backend_url=lambda: 'http://fixture', get_authenticated_profile=object(),
            search_results=object(), configured_agent_model=lambda: model,
            connect_bid_routes=lambda *a, **kw: calls.append(kw), print=lambda *a: None)
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
        self.assertIs(calls[0]['agent_model'], model)

    def test_configured_model_auth_scoring_and_missing_profile(self):
        cases = load_cases(); table = scoring_table(cases['scoring_templates'][0])
        profile = deepcopy(cases['profiles'][0]); opened = []; closed = []
        class Client:
            def __init__(self, **kw):
                opened.append(True); self.chat = NS(completions=NS(create=self.create))
            async def __aenter__(self): return self
            async def __aexit__(self, *args): closed.append(True)
            async def create(self, **request):
                calls = [] if any(m['role']=='tool' for m in request['messages']) else [
                    NS(id=i['id'], type='function', function=NS(name='calc_score',
                        arguments=json.dumps({'item_id': i['id']}))) for i in table['items']]
                return NS(model='fixture', choices=[NS(message=NS(content='', tool_calls=calls))],
                          usage=NS(prompt_tokens=100, completion_tokens=20))
        def auth(authorization: str | None = Header(None)):
            if authorization != 'Bearer fixture': raise HTTPException(401)
            return deepcopy(profile)
        app = FastAPI()
        app.include_router(create_bid_router(profile_dependency=auth, bids_provider=lambda: [],
            scoring_provider=lambda *a: table, checklist_provider=lambda *a: None, search=lambda *a: [],
            agent_model=configured_agent_model({'OPENAI_API_KEY': 'fixture'})))
        payload = {'bid_no': table['bid_no'], 'revision': table['revision']}
        with TestClient(app) as client, patch('openai.AsyncOpenAI', Client):
            self.assertEqual(client.post('/agent/score', json=payload).status_code, 401)
            self.assertFalse(opened)
            for status in ('complete', 'needs_input'):
                if status == 'needs_input': profile.pop('credit_rating', None)
                response = client.post('/agent/score', json=payload, headers={'Authorization': 'Bearer fixture'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['status'], status)
                if status == 'needs_input':
                    self.assertIn('credit_rating', response.json()['missing_fields'])
                    self.assertTrue(response.json()['questions'])
            self.assertEqual(opened, closed)
