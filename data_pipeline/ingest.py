"""전처리 데이터와 공식 웹 주제 다섯 개를 FAISS에 적재한다."""
import argparse
import json
from pathlib import Path
from project_env import load_env
from .build_dataset import DEFAULT_DATASET
from .knowledge import KnowledgeStore, ingest_processed
from .web_topics import ingest_topics, TOPICS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument("--web-only", action="store_true")
    mode.add_argument("--pdf-only", action="store_true")
    args = parser.parse_args()
    load_env()
    log=args.run_dir/"ingestion.json"
    result = json.loads(log.read_text()) if log.exists() else {}
    if not args.web_only:
        result["pdf"] = ingest_processed(args.run_dir, KnowledgeStore("pdf", model=args.embedding_model))
    if not args.pdf_only:
        ingest_topics(KnowledgeStore("web", model=args.embedding_model))
        result["web"] = KnowledgeStore("web").status()
    elif "web" not in result:
        result["web"] = KnowledgeStore("web").status()
    (args.run_dir / "ingestion.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
