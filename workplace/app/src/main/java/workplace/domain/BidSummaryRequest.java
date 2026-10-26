package workplace.domain;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.List;

/** RAG 서비스가 만든 공고 요약 JSON을 그대로 받는 저장 요청입니다. */
public record BidSummaryRequest(
        String bidNo,
        String revision,
        JsonNode summary,
        List<String> missing,
        Boolean needsReview,
        Boolean handoff,
        Long latencyMs
) {
}
