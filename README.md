# 나라장터 입찰공고 탐색·요약


- [공식 평가셋·원문 복원·재측정](rag-code-template_ext/evaluation/real/README.md)
- [평가 결과](rag-code-template_ext/evaluation/real/REPORT.md)
- [채점 에이전트 실행·응답 계약](rag-code-template_ext/bid_logic/AGENT_RUN.md)

서비스는 실시간 검색을 사용하고, 평가는 `rag-code-template_ext/evaluation/real/bids.csv`와
`manifest.json`의 고정 20건을 사용합니다. 정답의 사람 검토는 아직 pending입니다.

실행 안내: [데이터 파이프라인](data_pipeline/README.md),
[RAG 서버](rag-code-template_ext/RUN.md), [인증 서버](workplace/README_BACKEND.md).
