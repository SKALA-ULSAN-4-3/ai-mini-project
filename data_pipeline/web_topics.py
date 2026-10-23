"""지정된 공식 원문의 본문을 내려받아 다섯 웹 주제를 누적 적재한다."""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.parse import urlparse, urljoin, parse_qs

import httpx
from bs4 import BeautifulSoup

from .knowledge import KnowledgeStore, ROOT
from .prepare_documents import split_text
from .privacy import mask_personal, extract_contacts

TOPICS = {
    "협상에 의한 계약 제안서 평가 기준": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000273638",
    "소프트웨어사업 제안요청서 작성 가이드": "https://opengov.seoul.go.kr/og/com/download.php?dname=guide.pdf&dtype=basic&nid=23540375&rid=F0000086075049&uri=%2Ffiles%2Fdcdata%2F100024%2F20210819%2FF0000086075049.pdf",
    "용역 적격심사 기준": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000272418",
    "공동수급 표준협정서": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000275812",
    "나라장터 입찰참가자격 등록": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000274756",
}


def approved_url(url):
    p = urlparse(url)
    host = (p.hostname or "").lower()
    return p.scheme == "https" and not p.username and not p.password and p.port in (None, 443) and (
        host.endswith(".go.kr") or host in ("swit.or.kr", "www.swit.or.kr", "nipa.kr", "www.nipa.kr"))


def download(url):
    with httpx.Client(timeout=45, follow_redirects=False) as client:
        for _ in range(8):
            if not approved_url(url):
                raise ValueError("공식 HTTPS 원문 URL만 허용됩니다.")
            with client.stream("GET", url, headers={"User-Agent": "BidCorpus/1.0"}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                result = bytearray()
                for block in response.iter_bytes():
                    result.extend(block)
                    if len(result) > 20 * 1024 * 1024:
                        raise ValueError("웹 원문 20MB 초과")
                return bytes(result), url
    raise ValueError("리디렉션 횟수 초과")


def topic_records(topic, url=None, cache_root=None, refresh=False):
    if url is None:
        if topic not in TOPICS:
            raise ValueError("등록되지 않은 주제입니다. 공식 원문 url을 지정하세요.")
        url = TOPICS[topic]
    if not approved_url(url):
        raise ValueError("지원하지 않는 URL")
    root = Path(cache_root or ROOT / "data/web")
    root.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256((topic+url).encode()).hexdigest()
    cached = root / (identity + ".json")
    if cached.exists() and not refresh:
        return json.loads(cached.read_text())["records"]
    raw, resolved = download(url)
    original_digest = hashlib.sha256(raw).hexdigest()
    if raw.startswith(b"%PDF-"):
        from pypdf import PdfReader
        texts = [p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages]
        title = topic
    else:
        soup = BeautifulSoup(raw, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else topic
        # 법령정보센터는 본문을 별도 AJAX 엔드포인트로 로드한다.
        seq = re.search(r'name="admRulSeq"[^>]*value="(\d+)"', raw.decode("utf-8", errors="replace"))
        if "law.go.kr" in resolved and seq:
            body_url = f"https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq={seq[1]}&joTpYn=Y&languageType=KO&chrClsCd=010202"
            body, _ = download(body_url)
            soup = BeautifulSoup(body, "html.parser")
        for tag in soup.select("script,style,nav,header,footer,noscript"):
            tag.decompose()
        main = soup.select_one("#conScroll, #contentBody, #bodyContent, article, main") or soup
        texts = [main.get_text("\n", strip=True)]
    if sum(len(t.strip()) for t in texts) < 400:
        raise ValueError("공식 본문이 너무 짧거나 추출되지 않았습니다.")
    stamp = datetime.now(timezone.utc).isoformat()
    records = []
    for page, text in enumerate(texts, 1):
        text = mask_personal(text)
        for offset, (start, end, part) in enumerate(split_text(text), 1):
            row = dict(topic=topic, title=title, text=part, source_url=url, resolved_url=resolved,
                       collected_at=stamp, page=page, file_name=topic, citation=f"{title} p.{page}",
                       group_id="web:"+url, sha256=original_digest,
                       contacts=extract_contacts(part), privacy_policy="mask_names_preserve_contacts_v1")
            row["chunk_id"] = hashlib.sha256((topic+url+original_digest+str(page)+str(offset)+part).encode()).hexdigest()
            records.append(row)
    (root / (identity + ".source")).write_bytes(raw)
    cached.write_text(json.dumps({"topic": topic, "url": url, "records": records}, ensure_ascii=False))
    return records


def ingest_topics(store=None):
    store = store or KnowledgeStore("web")
    results = []
    for topic in TOPICS:
        result = store.upsert(topic_records(topic))
        results.append({"topic": topic, "chunks": result["chunks"]})
        print(f"웹 주제 적재: {topic}", flush=True)
    return results
