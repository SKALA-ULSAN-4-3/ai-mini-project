# 최종 통합 전달 목록

이 문서는 정하윤 담당 변경과 검증 결과를 모은다. Git 브랜치 변경·커밋·푸시·병합·팀원 메시지 전송은 수행하지 않았다.

## 준비 완료

- 고정 평가 20건 지정, 원문 복원 스크립트와 해시 검증.
- 추천 마감 누락 보정과 전후 비교. 울산 P@5 80% → 100%; 서울 40%·제주 60% 유지.
- 에이전트 서버 연결과 환경변수 설정, 정상·되묻기 응답 예시.
- Python 테스트 184개 통과 기록.
- 실제 Java/PostgreSQL·Bearer 인증·HTTP 채점·실제 모델 재채점 검증 완료: 각 63개 검사, 실제 채점표 264항목 일치.
- 프론트 전달 문서와 실행 가능한 인증 통합 검증 도구.

## 팀에서 이어서 확인할 것

- [ ] 신한수: FRONTEND_HANDOFF.md의 호출 함수·버튼·결과 비교·되묻기 화면 구현
- [ ] 손수경: 실제 실행/배포 환경의 DB_PASSWORD·JWT_SECRET·BACKEND_URL 준비와 인증 서버 기동
- [ ] 연결 후 실제 전체 RAG 서버·문서 추출·브라우저 흐름 검증
- [ ] 다른 팀원 PC에서 원문 복원·추천 라벨 테스트 재현
- [ ] 손경락: 기획서의 공식 평가셋·평가 방법 설명을 실제 파일과 일치시킴
- [ ] 사용자가 직접 정답을 검토하고 확인 범위만 gold.review와 REPORT에 기록
- [ ] 전체 검증 후 팀 절차로 최종 코드 통합

## 변경 파일 범위

- bid_logic/notice_metadata.py, notice_metadata.json, tests/test_notice_metadata.py: 마산 지역제한·영진 단계별 기한 및 경계 검증

- bid_logic/agent_config.py, rag_external-web_pdf_closed_llm.py: 서버 에이전트 연결
- bid_logic/restore_sources.py: 원문 복원
- bid_logic/evaluate_recommendation_change.py, evaluation/real/bids.csv, metadata-corrections.json: 마감 보정·평가
- tests/test_agent_config.py, test_source_restore.py, test_recommendation_change.py: 검증
- tools/verify_authenticated_agent.py: 실제 인증 HTTP 통합 검증 도구
- bid_logic/AGENT_RUN.md, FRONTEND_HANDOFF.md: 실행·API 전달
- evaluation/real/README.md, REPORT.md, AUTH_INTEGRATION.md와 JSON 결과: 재현·검증 기록
- AI_SOURCE_REVIEW.md와 JSON: 팀 공용 AI 검토 기록. 개인 기록지 PERSONAL_REVIEW.md는 Git 공유 제외

기존 평가 결과 JSON과 과거 AI 검토는 각 파일의 범위·날짜를 유지한다. 최신 상태는 REPORT.md 상단과 AUTH_INTEGRATION.md를 확인한다.
