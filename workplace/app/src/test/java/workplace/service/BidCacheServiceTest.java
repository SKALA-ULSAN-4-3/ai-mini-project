package workplace.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import workplace.domain.CacheResponse;
import workplace.domain.CachedResult;
import workplace.domain.CompanyProfile;
import workplace.domain.CompanyProfileRequest;
import workplace.domain.RfpCacheRequest;
import workplace.domain.SearchCacheRequest;
import workplace.exception.ValidationException;
import workplace.repository.BidCacheRepository;
import workplace.repository.CompanyProfileRepository;

import java.time.Instant;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 외부 DB 없이 캐시 키 정규화·프로필 변경·공고 차수 규칙을 검증합니다. */
class BidCacheServiceTest {

    private static final String BUSINESS_NUMBER = "1234567890";
    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void equivalentSearchConditionsUseSameCacheKey() {
        RecordingCacheRepository cache = new RecordingCacheRepository();
        BidCacheService service = service(cache, profile(Instant.parse("2026-10-26T00:00:00Z")));
        JsonNode result = mapper.createObjectNode().putArray("bids");

        service.saveSearch(BUSINESS_NUMBER, search(List.of(" AI ", "소프트웨어", "ai"), result));
        String firstHash = cache.lastRequestHash;
        service.saveSearch(BUSINESS_NUMBER, search(List.of("소프트웨어", "AI"), result));

        assertEquals(firstHash, cache.lastRequestHash);
        assertEquals(List.of("ai", "소프트웨어"), cache.lastQueries);
        assertEquals(100, cache.lastLimit);
    }

    @Test
    void profileUpdateChangesSearchCacheKey() {
        RecordingCacheRepository cache = new RecordingCacheRepository();
        MutableProfileRepository profiles = new MutableProfileRepository(
                profile(Instant.parse("2026-10-26T00:00:00Z"))
        );
        BidCacheService service = new BidCacheService(
                cache,
                new CompanyProfileService(profiles)
        );

        service.findSearch(BUSINESS_NUMBER, search(List.of("AI"), null));
        String before = cache.lastRequestHash;
        profiles.profile = profile(Instant.parse("2026-10-26T01:00:00Z"));
        service.findSearch(BUSINESS_NUMBER, search(List.of("AI"), null));

        assertFalse(before.equals(cache.lastRequestHash));
    }

    @Test
    void savesAndFindsRfpByBidAndRevision() {
        RecordingCacheRepository cache = new RecordingCacheRepository();
        BidCacheService service = service(cache, profile(Instant.now()));
        JsonNode result = mapper.createObjectNode().put("status", "completed");

        CacheResponse saved = service.saveRfp(
                "R26BK01789933",
                new RfpCacheRequest("001", result)
        );
        CacheResponse found = service.findRfp("R26BK01789933", "001");

        assertTrue(saved.cached());
        assertTrue(found.cached());
        assertEquals("completed", found.result().get("status").asText());
        assertEquals("001", cache.lastRevision);
    }

    @Test
    void rejectsInvalidSearchAndScalarResult() {
        BidCacheService service = service(
                new RecordingCacheRepository(),
                profile(Instant.now())
        );

        assertThrows(ValidationException.class, () -> service.findSearch(
                BUSINESS_NUMBER,
                new SearchCacheRequest(
                        LocalDate.of(2026, 10, 27),
                        LocalDate.of(2026, 10, 26),
                        List.of("AI"),
                        100,
                        null
                )
        ));
        assertThrows(ValidationException.class, () -> service.saveRfp(
                "R26BK01789933",
                new RfpCacheRequest("000", mapper.getNodeFactory().textNode("잘못된 결과"))
        ));
    }

    private BidCacheService service(
            RecordingCacheRepository cache,
            CompanyProfile profile
    ) {
        return new BidCacheService(
                cache,
                new CompanyProfileService(new MutableProfileRepository(profile))
        );
    }

    private SearchCacheRequest search(List<String> queries, JsonNode result) {
        return new SearchCacheRequest(
                LocalDate.of(2026, 10, 1),
                LocalDate.of(2026, 10, 26),
                queries,
                null,
                result
        );
    }

    private CompanyProfile profile(Instant updatedAt) {
        return new CompanyProfile(
                1L,
                BUSINESS_NUMBER,
                "소프트웨어 개발",
                null,
                "울산광역시",
                "중소기업",
                null,
                null,
                null,
                null,
                null,
                null,
                List.of("AI"),
                updatedAt.minus(1, ChronoUnit.DAYS),
                updatedAt
        );
    }

    private static final class MutableProfileRepository implements CompanyProfileRepository {
        private CompanyProfile profile;

        private MutableProfileRepository(CompanyProfile profile) {
            this.profile = profile;
        }

        @Override
        public Optional<CompanyProfile> findByBusinessRegistrationNumber(String number) {
            return profile.businessRegistrationNumber().equals(number)
                    ? Optional.of(profile)
                    : Optional.empty();
        }

        @Override
        public CompanyProfile save(String number, CompanyProfileRequest request) {
            throw new UnsupportedOperationException("이 테스트에서는 저장하지 않습니다.");
        }
    }

    private static final class RecordingCacheRepository implements BidCacheRepository {
        private String lastRequestHash;
        private List<String> lastQueries;
        private int lastLimit;
        private String lastRevision;
        private CachedResult rfp;

        @Override
        public Optional<CachedResult> findSearch(String number, String requestHash) {
            lastRequestHash = requestHash;
            return Optional.empty();
        }

        @Override
        public CachedResult saveSearch(
                String number,
                String requestHash,
                LocalDate from,
                LocalDate to,
                List<String> queries,
                int limit,
                String profileFingerprint,
                JsonNode result
        ) {
            lastRequestHash = requestHash;
            lastQueries = queries;
            lastLimit = limit;
            return cached(result);
        }

        @Override
        public Optional<CachedResult> findRfp(String bidNo, String revision) {
            lastRevision = revision;
            return Optional.ofNullable(rfp);
        }

        @Override
        public CachedResult saveRfp(String bidNo, String revision, JsonNode result) {
            lastRevision = revision;
            rfp = cached(result);
            return rfp;
        }

        private CachedResult cached(JsonNode result) {
            Instant now = Instant.parse("2026-10-26T00:00:00Z");
            return new CachedResult(result, now, now.plus(24, ChronoUnit.HOURS));
        }
    }
}
