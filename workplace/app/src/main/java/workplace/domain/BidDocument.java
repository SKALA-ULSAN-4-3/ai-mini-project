package workplace.domain;

import java.time.Instant;

/** Storage에 보관된 공고 원본 PDF의 DB 메타데이터입니다. */
public record BidDocument(
        Long id,
        String bidNo,
        String revision,
        String fileName,
        String storageKey,
        long sizeBytes,
        String sourceUrl,
        Instant collectedAt
) {
}
