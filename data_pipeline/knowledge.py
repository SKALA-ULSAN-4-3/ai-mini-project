"""중복 없는 누적 FAISS 저장소. JSON 메타데이터와 원자적 세대 교체."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from .common import read_json, ROOT, directory_lock, read_jsonl, write_jsonl

import faiss
import numpy as np


INDEX_ROOT = Path(os.environ.get("BID_INDEX_ROOT", str(ROOT / "data" / "indexes")))


class Embedder:
    def __init__(self, model="text-embedding-3-small"):
        self.model = model

    def embed(self, texts):
        if self.model == "local-char-ngram-v1":
            result = np.zeros((len(texts), 2048), dtype="float32")
            for i, text in enumerate(texts):
                text = re.sub(r"\s+", " ", text.lower())
                for size in (2, 3, 4):
                    for offset in range(max(0, len(text) - size + 1)):
                        token = text[offset:offset+size]
                        digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
                        result[i, int.from_bytes(digest, "little") % 2048] += 1
            faiss.normalize_L2(result)
            return result
        from openai import OpenAI
        client = OpenAI(timeout=60, max_retries=2)
        vectors = []
        for start in range(0, len(texts), 64):
            response = client.embeddings.create(model=self.model, input=texts[start:start+64])
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda x: x.index))
        result = np.asarray(vectors, dtype="float32")
        faiss.normalize_L2(result)
        return result


class KnowledgeStore:
    def __init__(self, kind="pdf", root=None, model=None):
        if kind not in ("pdf", "web"):
            raise ValueError("지원 저장소: pdf, web")
        self.path = Path(root or INDEX_ROOT) / kind
        self.model = model or os.environ.get("BID_EMBEDDING_MODEL", "text-embedding-3-small")

    def locked(self):
        return directory_lock(self.path, ".lock")

    def load(self):
        pointer = self.path / "current.json"
        if not pointer.exists():
            return None, [], None
        generation = read_json(pointer)["generation"]
        if not re.fullmatch(r"[0-9a-f]{32}", generation):
            raise ValueError("잘못된 인덱스 세대")
        path = self.path / "generations" / generation
        manifest = read_json(path / "manifest.json")
        records = read_jsonl(path / "documents.jsonl")
        index = faiss.read_index(str(path / "index.faiss"))
        if index.ntotal != len(records):
            raise ValueError("FAISS와 출처 레코드 개수 불일치")
        return index, records, manifest

    def upsert(self, records, replace_all=False):
        if not records:
            return self.status()
        # group_id는 공고 첨부/웹 URL. 같은 그룹 재업로드는 기존 버전만 교체.
        incoming = {r["chunk_id"]: r for r in records if r.get("text", "").strip()}
        if not incoming:
            raise ValueError("적재 가능한 텍스트 없음")
        with self.locked():
            index, old, manifest = self.load()
            if manifest and manifest["embedding_model"] != self.model:
                raise ValueError("기존 임베딩 모델과 다릅니다. 별도 인덱스 경로를 사용하세요.")
            groups = {r["group_id"] for r in incoming.values()}
            old_map = {r["chunk_id"]: r for r in old}
            if set(incoming) <= old_map.keys() and all(old_map[k] == r for k, r in incoming.items()) and (not replace_all or set(incoming) == set(old_map)):
                return {**manifest, "added_chunks": 0}
            kept = [] if replace_all else [(i, r) for i, r in enumerate(old) if r["group_id"] not in groups]
            by_id = {r["chunk_id"]: i for i, r in enumerate(old)}
            reusable = {k for k in incoming if k in old_map and incoming[k]["text"] == old_map[k]["text"]}
            pending = [r for k, r in incoming.items() if k not in reusable]
            new_vectors = Embedder(self.model).embed([r["text"] for r in pending]) if pending else None
            vector_map = {r["chunk_id"]: new_vectors[i] for i, r in enumerate(pending)}
            final_records = [r for _, r in kept] + list(incoming.values())
            vectors = [index.reconstruct(i) for i, _ in kept]
            vectors.extend(index.reconstruct(by_id[k]) if k in reusable else vector_map[k] for k in incoming)
            matrix = np.asarray(vectors, dtype="float32")
            return self._save_generation(final_records, matrix, len(pending))

    def _save_generation(self, final_records, matrix, added_chunks):
        """완성된 파일 묶음을 쓴 뒤 current 포인터만 원자적으로 교체한다."""
        new_index = faiss.IndexFlatIP(matrix.shape[1])
        new_index.add(matrix)
        generation = uuid.uuid4().hex
        target = self.path / "generations" / generation
        target.mkdir(parents=True)
        faiss.write_index(new_index, str(target / "index.faiss"))
        write_jsonl(target / "documents.jsonl", final_records)
        manifest = dict(embedding_model=self.model, dimensions=matrix.shape[1], chunks=len(final_records),
                        documents=len({r["group_id"] for r in final_records}),
                        bids=len({(r.get("bid_no"), r.get("bid_order")) for r in final_records if r.get("bid_no")}),
                        topics=sorted({r["topic"] for r in final_records if r.get("topic")}),
                        updated_at=datetime.now(timezone.utc).isoformat(), generation=generation,
                        contacts_preserved=True, personal_names_masked=True)
        (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        temporary = self.path / "current.tmp"
        temporary.write_text(json.dumps({"generation": generation}))
        temporary.replace(self.path / "current.json")
        return {**manifest, "added_chunks": added_chunks}

    def status(self):
        _, _, manifest = self.load()
        return manifest or {"chunks": 0, "documents": 0, "bids": 0, "topics": []}


def ingest_processed(run_dir, store=None):
    path = Path(run_dir) / "processed" / "chunks.jsonl"
    records = read_jsonl(path)
    for row in records:
        row["group_id"] = f"{row['bid_no']}_{row['bid_order']}:{row['source_url']}"
        # 개인정보 정책 변경 시에도 과거 벡터를 잘못 재사용하지 않는다.
        row["chunk_id"] = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return (store or KnowledgeStore()).upsert(records, replace_all=True)
