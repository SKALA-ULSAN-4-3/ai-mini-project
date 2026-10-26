package workplace.service;

import com.fasterxml.jackson.databind.JsonNode;
import workplace.domain.CacheResponse;
import workplace.domain.CompanyProfile;
import workplace.domain.RfpCacheRequest;
import workplace.domain.SearchCacheRequest;
import workplace.exception.ValidationException;
import workplace.repository.BidCacheRepository;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.text.Normalizer;
import java.time.LocalDate;
import java.util.HexFormat;
import java.util.List;
import java.util.Locale;

/** 검색 조건 정규화, 회사 프로필 버전 반영과 캐시 유효성 규칙을 담당합니다. */
public final class BidCacheService {

    private static final int DEFAULT_SEARCH_LIMIT = 100;

    private final BidCacheRepository repository;
    private final CompanyProfileService profileService;

    public BidCacheService(
            BidCacheRepository repository,
            CompanyProfileService profileService
    ) {
        this.repository = repository;
        this.profileService = profileService;
    }

    public CacheResponse findSearch(
            String businessRegistrationNumber,
            SearchCacheRequest request
    ) {
        SearchKey key = searchKey(businessRegistrationNumber, request);
        return repository.findSearch(businessRegistrationNumber, key.requestHash())
                .map(CacheResponse::hit)
                .orElseGet(CacheResponse::miss);
    }

    public CacheResponse saveSearch(
            String businessRegistrationNumber,
            SearchCacheRequest request
    ) {
        SearchKey key = searchKey(businessRegistrationNumber, request);
        JsonNode result = requiredResult(request == null ? null : request.result());
        return CacheResponse.hit(repository.saveSearch(
                businessRegistrationNumber,
                key.requestHash(),
                key.from(),
                key.to(),
                key.queries(),
                key.limit(),
                key.profileFingerprint(),
                result
        ));
    }

    public CacheResponse findRfp(String bidNo, String revision) {
        return repository.findRfp(
                        BidIds.bidNo(bidNo),
                        BidIds.revision(revision)
                )
                .map(CacheResponse::hit)
                .orElseGet(CacheResponse::miss);
    }

    public CacheResponse saveRfp(String bidNo, RfpCacheRequest request) {
        if (request == null) {
            throw new ValidationException("제안요청서 캐시 요청 본문이 필요합니다.");
        }
        return CacheResponse.hit(repository.saveRfp(
                BidIds.bidNo(bidNo),
                BidIds.revision(request.revision()),
                requiredResult(request.result())
        ));
    }

    private SearchKey searchKey(
            String businessRegistrationNumber,
            SearchCacheRequest request
    ) {
        if (request == null) {
            throw new ValidationException("공고 검색 캐시 요청 본문이 필요합니다.");
        }

        LocalDate from = request.from();
        LocalDate to = request.to();
        if (from == null || to == null || from.isAfter(to)) {
            throw new ValidationException("from과 to에 올바른 검색 기간이 필요합니다.");
        }

        List<String> queries = normalizeQueries(request.queries());
        int limit = request.limit() == null ? DEFAULT_SEARCH_LIMIT : request.limit();
        if (limit < 1 || limit > 100) {
            throw new ValidationException("limit은 1 이상 100 이하 정수여야 합니다.");
        }

        CompanyProfile profile = profileService.get(businessRegistrationNumber);
        String profileFingerprint = sha256(
                businessRegistrationNumber + "\n" + profile.updatedAt()
        );
        String requestHash = sha256(String.join("\n",
                from.toString(),
                to.toString(),
                Integer.toString(limit),
                profileFingerprint,
                String.join("\u001F", queries)
        ));
        return new SearchKey(
                from,
                to,
                queries,
                limit,
                profileFingerprint,
                requestHash
        );
    }

    /** 검색어 순서·중복·대소문자 차이 때문에 같은 요청이 다른 키가 되지 않게 합니다. */
    private List<String> normalizeQueries(List<String> rawQueries) {
        if (rawQueries == null || rawQueries.isEmpty()) {
            throw new ValidationException("queries에 검색어를 한 개 이상 입력해야 합니다.");
        }
        List<String> queries = rawQueries.stream()
                .map(value -> value == null ? "" : Normalizer.normalize(
                        value,
                        Normalizer.Form.NFKC
                ).trim().toLowerCase(Locale.ROOT))
                .filter(value -> !value.isEmpty())
                .distinct()
                .sorted()
                .toList();
        if (queries.isEmpty() || queries.size() > 20) {
            throw new ValidationException("검색어는 중복을 제외하고 1개 이상 20개 이하여야 합니다.");
        }
        if (queries.stream().anyMatch(value -> value.length() > 200)) {
            throw new ValidationException("검색어 하나는 200자를 초과할 수 없습니다.");
        }
        return queries;
    }

    private JsonNode requiredResult(JsonNode result) {
        if (result == null || (!result.isObject() && !result.isArray())) {
            throw new ValidationException("result는 JSON 객체 또는 배열이어야 합니다.");
        }
        return result;
    }

    private String sha256(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256을 사용할 수 없습니다.", exception);
        }
    }

    private record SearchKey(
            LocalDate from,
            LocalDate to,
            List<String> queries,
            int limit,
            String profileFingerprint,
            String requestHash
    ) {
    }
}
