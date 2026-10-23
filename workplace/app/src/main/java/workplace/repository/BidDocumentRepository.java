package workplace.repository;

import workplace.domain.BidDocument;

import java.util.List;

/** 공고 원본 PDF 메타데이터 영속성 기능을 정의합니다. */
public interface BidDocumentRepository {

    boolean exists(String bidNo, String revision, String fileName);

    BidDocument save(
            String bidNo,
            String revision,
            String fileName,
            String storageKey,
            long sizeBytes,
            String sourceUrl
    );

    /** 차수가 null이면 해당 공고의 모든 차수를 돌려줍니다. */
    List<BidDocument> findByBid(String bidNo, String revision);
}
