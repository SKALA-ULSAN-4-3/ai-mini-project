package workplace.domain;

import com.fasterxml.jackson.databind.JsonNode;

import java.time.Instant;
import java.util.List;

/** 요약과 해당 공고의 원본 PDF 링크를 함께 내려 주는 응답입니다. */
public record BidSummaryView(
        String businessRegistrationNumber,
        String bidNo,
        String revision,
        JsonNode summary,
        List<String> missing,
        boolean needsReview,
        boolean handoff,
        Long latencyMs,
        Instant createdAt,
        Instant updatedAt,
        List<BidDocumentView> documents
) {

    public static BidSummaryView of(BidSummary summary, List<BidDocumentView> documents) {
        return new BidSummaryView(
                summary.businessRegistrationNumber(),
                summary.bidNo(),
                summary.revision(),
                summary.summary(),
                summary.missing(),
                summary.needsReview(),
                summary.handoff(),
                summary.latencyMs(),
                summary.createdAt(),
                summary.updatedAt(),
                documents
        );
    }
}
