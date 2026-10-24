package workplace.domain;

import java.time.Instant;

/** 응답 DTO: 공고별 상태 및 최초 선택·승인 시각. */
public record PipelineEntry(
        String bidNo, String revision, String status,
        Instant selectedAt, Instant approvedAt
) { }
