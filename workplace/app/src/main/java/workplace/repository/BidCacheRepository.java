package workplace.repository;

import com.fasterxml.jackson.databind.JsonNode;
import workplace.domain.CachedResult;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

/** 공고 검색·제안요청서 캐시의 영속화 기능을 정의합니다. */
public interface BidCacheRepository {

    Optional<CachedResult> findSearch(
            String businessRegistrationNumber,
            String requestHash
    );

    CachedResult saveSearch(
            String businessRegistrationNumber,
            String requestHash,
            LocalDate from,
            LocalDate to,
            List<String> queries,
            int limit,
            String profileFingerprint,
            JsonNode result
    );

    Optional<CachedResult> findRfp(String bidNo, String revision);

    CachedResult saveRfp(String bidNo, String revision, JsonNode result);
}
