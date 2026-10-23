"""실제 공고 평가 준비/실행. 빈 입력을 정답이나 0점 평가로 취급하지 않는다."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from .checklist import build_checklist, document_key
from .common import calendar_date, check_scope, identity, number, require_sources, seoul_time
from .recommendation import load_bids_csv, recommend_bids
from .scoring import calculate_scores

CSV_FIELDS = ["bid_no", "revision", "title", "agency", "published_at", "budget", "deadline",
              "regions", "industries", "licenses", "company_sizes", "certs", "filename", "url"]
JSON_FILES = {"profiles.json": [], "scoring_tables.json": [], "checklists.json": [],
              "hits.json": [], "gold.json": {"recommendations": [], "scores": [], "checklists": []}}


def initialize_dataset(directory):
    """실제 값/정답을 만들지 않고 빈 작성 틀만 생성한다. 기존 파일은 덮어쓰지 않는다."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    names = ["manifest.json", "bids.csv", *JSON_FILES]
    if any((directory / name).exists() for name in names):
        raise ValueError("이미 평가 파일이 있습니다. 새 디렉터리를 지정하세요.")
    manifest = {"schema_version": 1, "dataset_kind": "real", "from": None, "to": None,
                "now": None, "ranking_input_kind": "unmeasured", "embedding_model": None,
                "index_version": None, "targets": {"bids": 20, "profiles": 3, "score_bids": 5}}
    for name, value in {"manifest.json": manifest, **JSON_FILES}.items():
        (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (directory / "bids.csv").open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerow(CSV_FIELDS)


def load_dataset(directory):
    directory = Path(directory)
    result = {name.removesuffix(".json"): json.loads((directory / name).read_text(encoding="utf-8"))
              for name in ["manifest.json", *JSON_FILES]}
    result["bids"] = load_bids_csv(directory / "bids.csv")
    return result


def _index(rows, key, label):
    if not isinstance(rows, list):
        raise ValueError(f"{label}는 배열이어야 합니다.")
    result = {}
    for row in rows:
        identifier = key(row)
        if identifier in result:
            raise ValueError(f"{label} 식별자가 중복되었습니다: {identifier}")
        result[identifier] = row
    return result


def _reviewed(row):
    review = row.get("review", {})
    if review.get("status") != "verified" or not review.get("reviewer") or not review.get("reviewed_at"):
        return False
    seoul_time(review["reviewed_at"])
    return True


def _sources(row, bid_no, revision):
    require_sources(row)
    for source in row["sources"]:
        check_scope(source, bid_no, revision)
        if not source.get("filename") or not isinstance(source.get("page"), int) or isinstance(
                source.get("page"), bool) or source["page"] < 1:
            raise ValueError("검산용 출처에는 파일명과 1부터 시작하는 쪽수가 필요합니다.")
    return frozenset((s["bid_no"], s["revision"], s["filename"], s["page"]) for s in row["sources"])


def _check_inputs(data):
    """아직 채우지 못한 자료/검토 상태를 수집한다. 잘못된 계약은 ValueError."""
    m = data["manifest"]
    if m.get("schema_version") != 1 or m.get("dataset_kind") not in ("real", "synthetic"):
        raise ValueError("schema_version=1과 dataset_kind(real/synthetic)가 필요합니다.")
    targets = m["targets"]
    if set(targets) != {"bids", "profiles", "score_bids"} or any(
            isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in targets.values()):
        raise ValueError("평가 대상 수는 양의 정수여야 합니다.")
    if m["dataset_kind"] == "real" and targets != {"bids": 20, "profiles": 3, "score_bids": 5}:
        raise ValueError("실제 기획서 평가 규모는 공고 20건·프로필 3개·채점 공고 5건입니다.")
    issues = []
    for field in ("from", "to", "now"):
        if not m.get(field):
            issues.append(f"manifest.{field} 입력 필요")
    if m.get("from") and m.get("to") and calendar_date(m["from"]) > calendar_date(m["to"]):
        raise ValueError("평가 기간이 뒤집혔습니다.")
    if m.get("now"):
        seoul_time(m["now"])
    bids = _index(data["bids"], identity, "공고")
    profiles = _index(data["profiles"], lambda r: r["id"], "프로필")
    tables = _index(data["scoring_tables"], identity, "채점표")
    checklists = _index(data["checklists"], identity, "체크리스트")
    hits = _index(data["hits"], lambda r: r["profile_id"], "임베딩 결과")
    for name, actual, target in (("공고", len(bids), targets["bids"]),
                                 ("프로필", len(profiles), targets["profiles"]),
                                 ("채점표", len(tables), targets["score_bids"])):
        if actual != target:
            issues.append(f"{name}: {actual}/{target}개 준비")
    for key, table in tables.items():
        if key not in bids:
            raise ValueError("채점표가 공고 CSV에 없는 공고·차수를 참조합니다.")
        check_scope(table, *key)
        if not table.get("items"):
            raise ValueError("채점표 항목이 비었습니다.")
        _index(table["items"], lambda r: r["id"], "채점 항목")
        for item in table["items"]:
            check_scope(item, *key)
            _sources(item, *key)
    if set(checklists) != set(tables) or len(checklists) != targets["score_bids"]:
        issues.append("평가용 5개 공고의 체크리스트 추출 결과 필요")
    for key, extracted in checklists.items():
        if key not in bids:
            raise ValueError("체크리스트가 공고 CSV에 없는 공고·차수를 참조합니다.")
        check_scope(extracted, *key)
        for row in extracted["documents"] + extracted["schedule"]:
            check_scope(row, *key)
            _sources(row, *key)
    if set(hits) != set(profiles) or len(hits) != targets["profiles"]:
        issues.append("프로필별 임베딩 검색 결과 필요")
    for row in hits.values():
        if row["profile_id"] not in profiles:
            raise ValueError("검색 결과에 알 수 없는 프로필이 있습니다.")
        for hit in row["hits"]:
            if identity(hit) not in bids or number(hit["distance"]) < 0:
                raise ValueError("검색 결과의 공고 또는 L2 거리가 올바르지 않습니다.")
    if m["dataset_kind"] == "real" and (m.get("ranking_input_kind") != "actual_embeddings" or not
                                       m.get("embedding_model") or not m.get("index_version")):
        issues.append("실제 임베딩 결과와 모델명·인덱스 버전 기록 필요")
    gold = data["gold"]
    rec_gold = _index(gold["recommendations"], lambda r: r["profile_id"], "추천 정답")
    score_gold = _index(gold["scores"], lambda r: (*identity(r), r["profile_id"]), "점수 정답")
    list_gold = _index(gold["checklists"], lambda r: (*identity(r), r["profile_id"]), "서류 정답")
    expected_pairs = {(*key, p) for key in tables for p in profiles}
    if set(rec_gold) != set(profiles) or len(rec_gold) != targets["profiles"]:
        issues.append("프로필별 추천 정답 필요")
    if set(score_gold) != expected_pairs or len(score_gold) != targets["score_bids"] * targets["profiles"]:
        issues.append("공고 5건 × 프로필 3개 조합의 점수 정답 필요")
    if set(list_gold) != expected_pairs or len(list_gold) != targets["score_bids"] * targets["profiles"]:
        issues.append("공고·프로필별 서류 보유/일정 정답 필요")
    for row in gold["recommendations"]:
        _index(row["relevant"], identity, "추천 정답 공고")
        if row["profile_id"] not in profiles or any(identity(r) not in bids for r in row["relevant"]):
            raise ValueError("추천 정답의 프로필 또는 공고가 입력에 없습니다.")
        if not row.get("rationale"):
            raise ValueError("추천 정답 선정 근거가 필요합니다.")
        if not _reviewed(row):
            issues.append(f"추천 정답 사람 검토 필요: {row['profile_id']}")
    for row in gold["scores"]:
        key = identity(row)
        if key not in tables or row["profile_id"] not in profiles:
            raise ValueError("점수 정답의 공고·차수 또는 프로필이 입력에 없습니다.")
        expected = _index(row["items"], lambda r: r["id"], "정답 항목")
        if not expected or set(expected) != {r["id"] for r in tables[key]["items"]}:
            raise ValueError("정답에는 정량·정성·가격 항목 모두가 있어야 합니다.")
        for item in expected.values():
            _sources(item, *key)
            if not item.get("basis") or item.get("status") not in ("calculated", "manual", "missing_profile"):
                raise ValueError("정답 항목의 검산 근거와 상태가 필요합니다.")
            if item["status"] == "calculated":
                number(item["expected"])
            elif item["expected"] != "담당자 판단":
                raise ValueError("수동 판단 정답에 임의 점수를 넣을 수 없습니다.")
        if not _reviewed(row):
            issues.append(f"점수 정답 사람 검토 필요: {key}/{row['profile_id']}")
    for row in gold["checklists"]:
        key = identity(row)
        if key not in checklists or row["profile_id"] not in profiles:
            raise ValueError("서류 정답의 공고·차수 또는 프로필이 입력에 없습니다.")
        for item in row["documents"] + row["schedule"]:
            _sources(item, *key)
            if "due" not in item:
                raise ValueError("서류·일정 정답에 due를 명시하세요. 미확인은 null입니다.")
        for item in row["documents"]:
            if "owned" not in item or (item["owned"] is not None and not isinstance(item["owned"], bool)):
                raise ValueError("서류 정답의 owned는 boolean 또는 null이어야 합니다.")
        if not _reviewed(row):
            issues.append(f"서류 정답 사람 검토 필요: {key}/{row['profile_id']}")
    return issues, (bids, profiles, tables, checklists, hits, rec_gold, score_gold, list_gold)


def _due(value):
    if value is None:
        return None
    try:
        return seoul_time(value).isoformat()
    except (ValueError, TypeError):
        return value  # 날짜만 있는 기한도 그대로 비교하고 미확인 상태를 보존한다.


def evaluate_dataset(data):
    issues, indexed = _check_inputs(data)
    manifest = data["manifest"]
    report = {"dataset_kind": manifest["dataset_kind"], "human_verified": False,
              "status": "incomplete", "issues": issues, "metrics": None,
              "x2_comparison": None, "cost": None}
    if issues:
        return report
    bids, profiles, tables, checklists, hits, rec_gold, score_gold, list_gold = indexed
    recommendations, scores, lists = [], [], []
    for profile_id, gold in rec_gold.items():
        result = recommend_bids(list(bids.values()), profiles[profile_id], manifest["from"], manifest["to"],
                                now=manifest["now"], hits=hits[profile_id]["hits"])
        actual = {identity(row) for row in result["bids"]}
        expected = {identity(row) for row in gold["relevant"]}
        matches = len(actual & expected)
        recommendations.append({"profile_id": profile_id, "returned": len(actual),
                                "precision_at_5": matches / 5,
                                "precision_returned": matches / len(actual) if actual else 0,
                                "recall": matches / len(expected) if expected else None})
    for (bid_no, revision, profile_id), gold in score_gold.items():
        result = calculate_scores(tables[(bid_no, revision)], profiles[profile_id], bid_no, revision)
        actual = {row["id"]: row for row in result["items"]}
        kinds = {row["id"]: row.get("kind") for row in tables[(bid_no, revision)]["items"]}
        for expected in gold["items"]:
            row = actual[expected["id"]]
            score_match = (number(row["expected"]) == number(expected["expected"]) if (
                row["status"] == expected["status"] == "calculated") else row["expected"] == expected["expected"])
            scores.append({"bid_no": bid_no, "revision": revision, "profile_id": profile_id,
                           "item_id": row["id"], "expected": expected["expected"], "actual": row["expected"],
                           "kind": kinds[row["id"]],
                           "matched": row["status"] == expected["status"] and score_match and
                           _sources(row, bid_no, revision) == _sources(expected, bid_no, revision)})
    for (bid_no, revision, profile_id), gold in list_gold.items():
        result = build_checklist(checklists[(bid_no, revision)], profiles[profile_id], bid_no, revision,
                                 now=manifest["now"])
        def signatures(rows, collection):
            return Counter((document_key(r["doc"]) if collection == "documents" else r["event"],
                            r.get("owned") if collection == "documents" else None,
                            _due(r.get("due")), _sources(r, bid_no, revision)) for r in rows)
        details = {"bid_no": bid_no, "revision": revision, "profile_id": profile_id}
        for collection in ("documents", "schedule"):
            actual, expected = signatures(result[collection], collection), signatures(gold[collection], collection)
            details[collection] = {"missing": sum((expected - actual).values()),
                                   "extra": sum((actual - expected).values())}
        lists.append(details)
    quantitative = [row for row in scores if row["kind"] == "quantitative"]
    report.update(status="evaluated", human_verified=manifest["dataset_kind"] == "real", metrics={
        "recommendations": recommendations, "scores": scores,
        "score_item_accuracy": sum(r["matched"] for r in scores) / len(scores),
        "quantitative_item_accuracy": (sum(r["matched"] for r in quantitative) / len(quantitative)
                                       if quantitative else None), "checklists": lists})
    return report


def main():
    parser = argparse.ArgumentParser(description="실제 공고 평가 준비·검증")
    parser.add_argument("--init", type=Path, help="새 디렉터리에 빈 평가 틀 생성")
    parser.add_argument("--dataset", type=Path, help="평가 파일 디렉터리")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if bool(args.init) == bool(args.dataset):
        parser.error("--init 또는 --dataset 중 하나만 지정하세요.")
    try:
        if args.init:
            initialize_dataset(args.init)
            print(f"빈 평가 틀 생성: {args.init} (실제 자료/정답 입력 대기)")
            return 0
        report = evaluate_dataset(load_dataset(args.dataset))
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        if report["status"] == "incomplete":
            return 2
        metrics = report["metrics"]
        return int(metrics["score_item_accuracy"] < 1 or any(
            row[part][field] for row in metrics["checklists"]
            for part in ("documents", "schedule") for field in ("missing", "extra")))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"status": "invalid_input", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
