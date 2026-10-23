package workplace.domain;

import java.time.Instant;

/** 메타데이터와 제한 시간 다운로드 주소를 함께 내려 주는 응답입니다. */
public record BidDocumentView(
        Long id,
        String bidNo,
        String revision,
        String fileName,
        String storageKey,
        long sizeBytes,
        String sourceUrl,
        Instant collectedAt,
        String downloadUrl,
        Long downloadUrlExpiresIn
) {

    public static BidDocumentView of(
            BidDocument document,
            String downloadUrl,
            Long expiresIn
    ) {
        return new BidDocumentView(
                document.id(),
                document.bidNo(),
                document.revision(),
                document.fileName(),
                document.storageKey(),
                document.sizeBytes(),
                document.sourceUrl(),
                document.collectedAt(),
                downloadUrl,
                expiresIn
        );
    }
}
