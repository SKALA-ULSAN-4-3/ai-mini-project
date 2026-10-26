package workplace.repository;

import workplace.domain.BidSummary;
import workplace.domain.BidSummaryRequest;

import java.util.List;
import java.util.Optional;

/** 공고 요약 영속성 기능을 정의합니다. */
public interface BidSummaryRepository {

    /** 같은 사업자의 (bid_no, revision)이 같으면 덮어씁니다. */
    BidSummary save(String businessRegistrationNumber, BidSummaryRequest request);

    Optional<BidSummary> find(
            String businessRegistrationNumber,
            String bidNo,
            String revision
    );

    /** 차수를 지정하지 않으면 가장 높은 차수를 돌려줍니다. */
    Optional<BidSummary> findLatest(String businessRegistrationNumber, String bidNo);

    List<BidSummary> findAll(String businessRegistrationNumber, int limit, int offset);
}
