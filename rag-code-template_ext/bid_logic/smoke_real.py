"""실제 평가 입력으로 라우터를 확인한다. 테스트 앱 전용 인증이며 운영 JWT 검증이 아니다."""
import json
from pathlib import Path

from .api import create_bid_router
from .recommendation import load_bids_csv, profile_query
from .prepare_real import ROOT, write_json


def smoke(dataset, assets):
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.testclient import TestClient
    profiles=json.loads((dataset/"profiles.json").read_text())
    tables=json.loads((dataset/"scoring_tables.json").read_text())
    lists=json.loads((dataset/"checklists.json").read_text())
    bids=load_bids_csv(dataset/"bids.csv")
    hits={r["profile_id"]:r["hits"] for r in json.loads((dataset/"hits.json").read_text())}
    manifest=json.loads((dataset/"manifest.json").read_text())
    vectors=json.loads((assets/"embeddings.json").read_text())["vectors"]
    chunk_count=json.loads((dataset/"embedding-measurement.json").read_text())["chunks"]
    keys={(b["bid_no"],b["revision"]) for b in bids}
    active={"profile":profiles[0]}
    def auth(authorization:str|None=Header(None)):
        if authorization!="Bearer evaluation-only":raise HTTPException(401)
        return active["profile"]
    def title_similarity(query,titles):
        i=next(i for i,p in enumerate(profiles) if profile_query(p)==query)
        q=vectors[chunk_count+i]
        scores={b["title"]:sum(a*c for a,c in zip(q,v)) for b,v in zip(bids,vectors[chunk_count+len(profiles):])}
        return [scores[t] for t in titles]
    def provider(rows,no,revision):
        return next((r for r in rows if (r["bid_no"],r["revision"])==(no,revision)),None)
    app=FastAPI()
    app.include_router(create_bid_router(profile_dependency=auth,bids_provider=lambda:bids,
        scoring_provider=lambda no,rev:provider(tables,no,rev),checklist_provider=lambda no,rev:provider(lists,no,rev),
        search=lambda q,keys:[h for h in hits[active["profile"]["id"]] if (h["bid_no"],h["revision"]) in keys],
        title_similarity=title_similarity,loaded_keys_provider=lambda:keys,clock=lambda:manifest["now"],
        search_results_provider=lambda search_id,p:{"items":bids} if search_id=="fixed20-eval" else None))
    client=TestClient(app);headers={"Authorization":"Bearer evaluation-only"};checks=[]
    listing_url=f"/bids?from={manifest['from']}&to={manifest['to']}&search_id=fixed20-eval"
    response=client.get(listing_url)
    checks.append({"case":"unauthorized","status":response.status_code,"passed":response.status_code==401})
    for profile in profiles:
        active["profile"]=profile
        response=client.get(listing_url,headers=headers)
        checks.append({"case":"list","profile_id":profile["id"],"status":response.status_code,
                       "returned":len(response.json().get("bids",[])),"passed":response.status_code==200})
        selected=[{"bid_no":b["bid_no"],"revision":b["revision"]} for b in bids]
        response=client.post("/bids/recheck",headers=headers,json={"from":manifest["from"],"to":manifest["to"],"bids":selected})
        checks.append({"case":"recheck","profile_id":profile["id"],"status":response.status_code,
                       "passed":response.status_code==200 and len(response.json()["bids"])==20})
        for table in tables:
            for suffix in ("score","checklist"):
                response=client.get(f"/bids/{table['bid_no']}/{suffix}?revision={table['revision']}",headers=headers)
                checks.append({"case":suffix,"bid_no":table["bid_no"],"profile_id":profile["id"],"status":response.status_code,
                               "passed":response.status_code==200 and response.json().get("revision")==table["revision"]})
    result={"scope":"in-process TestClient using actual frozen data, cached real vectors, fake test-only auth",
            "production_jwt_verified":False,"ui_e2e_verified":False,"passed":sum(c["passed"] for c in checks),
            "total":len(checks),"checks":checks}
    write_json(dataset/"api-smoke.json",result)
    print(result["passed"],"/",result["total"],"actual-data route checks passed (test-only auth)")
    if result["passed"]!=result["total"]:raise SystemExit(1)


if __name__=="__main__":smoke(Path("evaluation/real"),ROOT/"data/evaluation-source-20261023")
