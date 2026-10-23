package workplace.domain;

import com.fasterxml.jackson.databind.JsonNode;

import java.time.Instant;
import java.util.List;

/** DB에 저장된 공고 요약 응답입니다. */
public record BidSummary(
        String businessRegistrationNumber,
        String bidNo,
        String revision,
        JsonNode summary,
        List<String> missing,
        boolean needsReview,
        boolean handoff,
        Long latencyMs,
        Instant createdAt,
        Instant updatedAt
) {
}
