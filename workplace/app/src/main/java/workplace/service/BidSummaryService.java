package workplace.service;

import workplace.domain.BidSummary;
import workplace.domain.BidSummaryRequest;
import workplace.exception.NotFoundException;
import workplace.exception.ValidationException;
import workplace.repository.BidSummaryRepository;

import java.util.LinkedHashSet;
import java.util.List;

/** 로그인한 사업자별 공고 요약의 검증과 저장·조회 유스케이스를 담당합니다. */
public final class BidSummaryService {

    private static final int MAX_PAGE_SIZE = 200;

    private final BidSummaryRepository repository;

    public BidSummaryService(BidSummaryRepository repository) {
        this.repository = repository;
    }

    /** URL의 공고번호가 기준이며, 본문에 bid_no가 있으면 같은 값이어야 합니다. */
    public BidSummary save(
            String businessRegistrationNumber,
            String pathBidNo,
            BidSummaryRequest request
    ) {
        if (request == null) {
            throw new ValidationException("요약 요청 본문이 필요합니다.");
        }

        String bidNo = BidIds.bidNo(pathBidNo);
        if (request.bidNo() != null && !request.bidNo().isBlank()
                && !bidNo.equals(request.bidNo().trim())) {
            throw new ValidationException("URL의 bid_no와 본문의 bid_no가 다릅니다.");
        }
        if (request.summary() == null || !request.summary().isObject()) {
            throw new ValidationException("summary는 JSON 객체여야 합니다.");
        }

        return repository.save(businessRegistrationNumber, new BidSummaryRequest(
                bidNo,
                BidIds.revision(request.revision()),
                request.summary(),
                missing(request.missing()),
                Boolean.TRUE.equals(request.needsReview()),
                Boolean.TRUE.equals(request.handoff()),
                request.latencyMs()
        ));
    }

    /** 차수를 생략하면 가장 높은 차수를 돌려줍니다. */
    public BidSummary get(
            String businessRegistrationNumber,
            String bidNo,
            String revision
    ) {
        String normalizedBidNo = BidIds.bidNo(bidNo);
        return (revision == null || revision.isBlank()
                ? repository.findLatest(businessRegistrationNumber, normalizedBidNo)
                : repository.find(
                        businessRegistrationNumber,
                        normalizedBidNo,
                        BidIds.revision(revision)))
                .orElseThrow(() -> new NotFoundException("저장된 공고 요약이 없습니다."));
    }

    public List<BidSummary> list(
            String businessRegistrationNumber,
            int limit,
            int offset
    ) {
        if (limit < 1 || limit > MAX_PAGE_SIZE || offset < 0) {
            throw new ValidationException(
                    "limit은 1~" + MAX_PAGE_SIZE + ", offset은 0 이상이어야 합니다."
            );
        }
        return repository.findAll(businessRegistrationNumber, limit, offset);
    }

    private List<String> missing(List<String> values) {
        if (values == null) {
            return List.of();
        }
        LinkedHashSet<String> normalized = new LinkedHashSet<>();
        for (String value : values) {
            if (value != null && !value.isBlank()) {
                normalized.add(value.trim());
            }
        }
        return List.copyOf(normalized);
    }
}
