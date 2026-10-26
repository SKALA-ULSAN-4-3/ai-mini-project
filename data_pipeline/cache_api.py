"""Java 백엔드의 검색·제안요청서 JSON 캐시 연결."""
import os
from urllib.parse import quote

import httpx


def _settings():
    base = os.environ.get("BACKEND_URL", "").strip().rstrip("/")
    key = os.environ.get("SERVICE_API_KEY", "").strip()
    return base, key


def _client(authorization=None):
    base, key = _settings()
    if not base or not key:
        return None, None
    headers = {"X-Service-Key": key}
    if authorization:
        headers["Authorization"] = authorization
    return httpx.Client(timeout=httpx.Timeout(10, connect=3), follow_redirects=False,
                        headers=headers), base


def lookup_search(start, end, queries, limit, authorization):
    client, base = _client(authorization)
    if client is None:
        return {"status": "not_configured", "cached": False}
    try:
        with client:
            response = client.post(base + "/api/cache/search/lookup", json={
                "from": str(start), "to": str(end), "queries": queries, "limit": limit
            })
        if response.status_code != 200:
            return {"status": "failed", "cached": False,
                    "error": f"검색 캐시 조회 HTTP {response.status_code}",
                    "auth_failed": response.status_code in (401, 403)}
        payload = response.json()
        return {"status": "hit" if payload.get("cached") else "miss",
                "cached": bool(payload.get("cached")), "result": payload.get("result")}
    except (httpx.HTTPError, ValueError):
        return {"status": "failed", "cached": False, "error": "검색 캐시 조회 연결 실패"}


def save_search(start, end, queries, limit, result, authorization):
    client, base = _client(authorization)
    if client is None:
        return {"status": "not_configured"}
    try:
        with client:
            response = client.put(base + "/api/cache/search", json={
                "from": str(start), "to": str(end), "queries": queries,
                "limit": limit, "result": result
            })
        if response.status_code != 200:
            return {"status": "failed", "error": f"검색 캐시 저장 HTTP {response.status_code}",
                    "auth_failed": response.status_code in (401, 403)}
        return {"status": "saved"}
    except (httpx.HTTPError, ValueError):
        return {"status": "failed", "error": "검색 캐시 저장 연결 실패"}


def lookup_rfp(bid_no, revision):
    client, base = _client()
    if client is None:
        return {"status": "not_configured", "cached": False}
    try:
        with client:
            response = client.get(base + "/api/cache/rfp/" + quote(str(bid_no), safe=""),
                                  params={"revision": revision})
        if response.status_code != 200:
            return {"status": "failed", "cached": False,
                    "error": f"제안요청서 캐시 조회 HTTP {response.status_code}",
                    "auth_failed": response.status_code in (401, 403)}
        payload = response.json()
        return {"status": "hit" if payload.get("cached") else "miss",
                "cached": bool(payload.get("cached")), "result": payload.get("result")}
    except (httpx.HTTPError, ValueError):
        return {"status": "failed", "cached": False, "error": "제안요청서 캐시 조회 연결 실패"}


def save_rfp(bid_no, revision, result):
    client, base = _client()
    if client is None:
        return {"status": "not_configured"}
    try:
        with client:
            response = client.put(base + "/api/cache/rfp/" + quote(str(bid_no), safe=""),
                                  json={"revision": revision, "result": result})
        if response.status_code != 200:
            return {"status": "failed", "error": f"제안요청서 캐시 저장 HTTP {response.status_code}",
                    "auth_failed": response.status_code in (401, 403)}
        return {"status": "saved"}
    except (httpx.HTTPError, ValueError):
        return {"status": "failed", "error": "제안요청서 캐시 저장 연결 실패"}
