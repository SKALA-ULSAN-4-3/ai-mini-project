"""기존 서버의 실제 import·등록 함수를 LLM/DB 초기화 없이 검증한다."""

import ast
from pathlib import Path


def load_integration(*, app=None, base_dir=None):
    from fastapi import FastAPI

    source = Path(__file__).resolve().parents[1] / "rag_external-web_pdf_closed_llm.py"
    text = source.read_text(encoding="utf-8")
    parsed = ast.parse(text)
    nodes = [node for node in parsed.body if (
        isinstance(node, ast.ImportFrom) and (node.module or "").startswith("bid_logic")
    ) or (isinstance(node, ast.FunctionDef) and node.name == "register_bid_routes")]
    namespace = {"app": app if app is not None else FastAPI(),
                 "BASE_DIR": base_dir or source.parent, "VECTORSTORE_PDF": None}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    return namespace
