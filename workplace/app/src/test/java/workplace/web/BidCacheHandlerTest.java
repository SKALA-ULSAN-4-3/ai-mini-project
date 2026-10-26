package workplace.web;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import workplace.domain.CachedResult;
import workplace.domain.CompanyProfile;
import workplace.domain.CompanyProfileRequest;
import workplace.domain.User;
import workplace.repository.BidCacheRepository;
import workplace.repository.CompanyProfileRepository;
import workplace.security.JwtProvider;
import workplace.service.BidCacheService;
import workplace.service.CompanyProfileService;
import workplace.web.handler.BidCacheHandler;

import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Instant;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 실제 HTTP 서버에서 캐시 API의 이중 인증과 응답 계약을 검증합니다. */
class BidCacheHandlerTest {

    private static final String SERVICE_KEY = "test-service-key";
    private static final String BUSINESS_NUMBER = "1234567890";

    private final ObjectMapper mapper = new JsonCodec().objectMapper();
    private final HttpClient client = HttpClient.newHttpClient();
    private HttpServer server;
    private String baseUrl;
    private String accessToken;

    @BeforeEach
    void start() throws Exception {
        User user = new User(
                BUSINESS_NUMBER,
                "hash",
                "테스트 주식회사",
                "울산광역시 남구",
                "정보통신업",
                "소프트웨어 개발 및 공급업",
                "부"
        );
        JwtProvider jwtProvider = new JwtProvider(
                "test-secret-that-is-long-enough-for-hmac-sha256",
                "test",
                3600
        );
        accessToken = jwtProvider.createAccessToken(user);

        CompanyProfile profile = new CompanyProfile(
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
                Instant.parse("2026-10-25T00:00:00Z"),
                Instant.parse("2026-10-26T00:00:00Z")
        );
        BidCacheService cacheService = new BidCacheService(
                new MemoryCacheRepository(),
                new CompanyProfileService(new SingleProfileRepository(profile))
        );
        HttpResponses responses = new HttpResponses(mapper);
        BidCacheHandler handler = new BidCacheHandler(
                new CurrentUserResolver(jwtProvider),
                new ServiceKeyAuthenticator(SERVICE_KEY),
                cacheService,
                new RequestBodies(mapper),
                responses
        );

        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext(
                "/api/cache",
                new ErrorHandlingHandler(handler, responses)
        );
        server.start();
        baseUrl = "http://127.0.0.1:" + server.getAddress().getPort();
    }

    @AfterEach
    void stop() {
        server.stop(0);
    }

    @Test
    void searchCacheRequiresServiceKeyAndUserToken() throws Exception {
        String body = """
                {
                  "from":"2026-10-01",
                  "to":"2026-10-26",
                  "queries":["AI"],
                  "limit":100,
                  "result":{"bids":[{"bid_no":"R26BK1"}]}
                }
                """;

        assertEquals(401, send("PUT", "/api/cache/search", body, null, accessToken).statusCode());
        assertEquals(401, send("PUT", "/api/cache/search", body, SERVICE_KEY, null).statusCode());

        HttpResponse<String> saved = send(
                "PUT",
                "/api/cache/search",
                body,
                SERVICE_KEY,
                accessToken
        );
        assertEquals(200, saved.statusCode());
        assertTrue(mapper.readTree(saved.body()).get("cached").asBoolean());

        String lookupBody = """
                {"from":"2026-10-01","to":"2026-10-26","queries":["ai"],"limit":100}
                """;
        JsonNode found = mapper.readTree(send(
                "POST",
                "/api/cache/search/lookup",
                lookupBody,
                SERVICE_KEY,
                accessToken
        ).body());
        assertTrue(found.get("cached").asBoolean());
        assertEquals("R26BK1", found.at("/result/bids/0/bid_no").asText());
    }

    @Test
    void rfpCacheIsSharedAndRequiresOnlyServiceKey() throws Exception {
        String body = """
                {"revision":"001","result":{"status":"completed","files":[]}}
                """;

        assertEquals(401, send(
                "PUT",
                "/api/cache/rfp/R26BK1",
                body,
                null,
                null
        ).statusCode());
        assertEquals(200, send(
                "PUT",
                "/api/cache/rfp/R26BK1",
                body,
                SERVICE_KEY,
                null
        ).statusCode());

        JsonNode found = mapper.readTree(send(
                "GET",
                "/api/cache/rfp/R26BK1?revision=001",
                null,
                SERVICE_KEY,
                null
        ).body());
        assertTrue(found.get("cached").asBoolean());
        assertEquals("completed", found.at("/result/status").asText());
    }

    @Test
    void cacheMissReturnsTwoHundredWithCachedFalse() throws Exception {
        JsonNode response = mapper.readTree(send(
                "GET",
                "/api/cache/rfp/UNKNOWN?revision=000",
                null,
                SERVICE_KEY,
                null
        ).body());

        assertFalse(response.get("cached").asBoolean());
        assertTrue(response.get("result").isNull());
    }

    private HttpResponse<String> send(
            String method,
            String path,
            String body,
            String serviceKey,
            String token
    ) throws Exception {
        HttpRequest.Builder request = HttpRequest.newBuilder(URI.create(baseUrl + path))
                .method(
                        method,
                        body == null
                                ? HttpRequest.BodyPublishers.noBody()
                                : HttpRequest.BodyPublishers.ofString(body)
                );
        if (serviceKey != null) {
            request.header("X-Service-Key", serviceKey);
        }
        if (token != null) {
            request.header("Authorization", "Bearer " + token);
        }
        return client.send(request.build(), HttpResponse.BodyHandlers.ofString());
    }

    private record SingleProfileRepository(
            CompanyProfile profile
    ) implements CompanyProfileRepository {

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

    private static final class MemoryCacheRepository implements BidCacheRepository {
        private final Map<String, CachedResult> searches = new HashMap<>();
        private final Map<String, CachedResult> rfps = new HashMap<>();

        @Override
        public Optional<CachedResult> findSearch(String number, String requestHash) {
            return Optional.ofNullable(searches.get(number + "/" + requestHash));
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
            CachedResult cached = cached(result);
            searches.put(number + "/" + requestHash, cached);
            return cached;
        }

        @Override
        public Optional<CachedResult> findRfp(String bidNo, String revision) {
            return Optional.ofNullable(rfps.get(bidNo + "/" + revision));
        }

        @Override
        public CachedResult saveRfp(String bidNo, String revision, JsonNode result) {
            CachedResult cached = cached(result);
            rfps.put(bidNo + "/" + revision, cached);
            return cached;
        }

        private CachedResult cached(JsonNode result) {
            Instant now = Instant.parse("2026-10-26T00:00:00Z");
            return new CachedResult(result, now, now.plus(24, ChronoUnit.HOURS));
        }
    }
}
