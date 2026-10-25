"""환경변수로 X2 모델을 구성하며 요청 사이에 사용량을 공유하지 않는다."""
import os
from .agent_model import OpenAIChatModel


def configured_agent_model(environ=None):
    env = os.environ if environ is None else environ
    enabled = env.get('BID_AGENT_ENABLED', 'true').strip().lower()
    if enabled not in {'true', 'false'}:
        raise ValueError('BID_AGENT_ENABLED는 true 또는 false여야 합니다.')
    if enabled == 'false':
        return None
    key = env.get('OPENAI_API_KEY', '').strip()
    if not key:
        raise ValueError('X2 채점에는 OPENAI_API_KEY가 필요합니다.')
    model = env.get('BID_AGENT_MODEL', 'gpt-4o').strip()
    if not model:
        raise ValueError('BID_AGENT_MODEL이 비어 있습니다.')

    async def call(messages, specs):
        from openai import AsyncOpenAI
        async with AsyncOpenAI(api_key=key, timeout=45, max_retries=0) as client:
            return await OpenAIChatModel(client, model=model)(messages, specs)
    return call
