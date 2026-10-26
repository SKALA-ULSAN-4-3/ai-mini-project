package workplace.web;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import workplace.domain.BidDocument;
import workplace.domain.BidSummary;
import workplace.domain.BidSummaryRequest;
import workplace.domain.User;
import workplace.exception.ConflictException;
import workplace.repository.BidDocumentRepository;
import workplace.repository.BidSummaryRepository;
import workplace.security.JwtProvider;
import workplace.service.BidDocumentService;
import workplace.service.BidSummaryService;
import workplace.storage.DocumentStorage;
import workplace.web.handler.BidHandler;

import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpRequest.BodyPublishers;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 실제 HttpServer 위에서 /api/bids 경로·인증·저장 흐름을 가짜 저장소로 검증합니다. */
class BidHandlerTest {

    private static final String SERVICE_KEY = "test-service-key";
    private static final byte[] PDF = "%PDF-1.4 test".getBytes(StandardCharsets.UTF_8);

    private final ObjectMapper mapper = new JsonCodec().objectMapper();
    private final HttpClient client = HttpClient.newHttpClient();
    private final FakeStorage storage = new FakeStorage();
    private HttpServer server;
    private String base;
    private String userToken;
    private String otherUserToken;

    @BeforeEach
    void start() throws Exception {
        JwtProvider jwt = new JwtProvider(
                "test-secret-that-is-long-enough-for-hmac-sha256", "test", 3600);
        userToken = jwt.createAccessToken(new User(
                "1234567890", "hash", "테스트 주식회사", "주소", "업태", "업종", "부"));

        otherUserToken = jwt.createAccessToken(new User(
                "2222222222", "hash", "다른 주식회사", "주소", "업태", "업종", "부"));

        HttpResponses responses = new HttpResponses(mapper);
        BidHandler handler = new BidHandler(
                new CurrentUserResolver(jwt),
                new ServiceKeyAuthenticator(SERVICE_KEY),
                new BidSummaryService(new FakeSummaryRepository()),
                new BidDocumentService(new FakeDocumentRepository(), storage),
                new RequestBodies(mapper),
                responses
        );
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/bids", new ErrorHandlingHandler(handler, responses));
        server.start();
        base = "http://127.0.0.1:" + server.getAddress().getPort() + "/api/bids";
    }

    @AfterEach
    void stop() {
        server.stop(0);
    }

    @Test
    void savesSummaryThenReadsItBackWithSameJson() throws Exception {
        String body = """
                {"bid_no":"R26BK1","revision":"000",
                 "summary":{"budget":{"value":"1억원","source":"공고.pdf p.3",
                   "source_refs":[{"page":3}]}},
                 "missing":["eligibility"],"needs_review":true,"handoff":false,"latency_ms":1234}
                """;

        HttpResponse<String> put = send("PUT", "/R26BK1/summary", body, null, userToken);
        assertEquals(200, put.statusCode());

        HttpResponse<String> get = send("GET", "/R26BK1/summary", null, null, userToken);
        assertEquals(200, get.statusCode());
        JsonNode json = mapper.readTree(get.body());
        assertEquals("1억원", json.at("/summary/budget/value").asText());
        assertEquals(3, json.at("/summary/budget/source_refs/0/page").asInt());
        assertEquals("eligibility", json.at("/missing/0").asText());
        assertTrue(json.get("needs_review").asBoolean());
        assertEquals(1234, json.get("latency_ms").asInt());
    }

    @Test
    void putOverwritesSameBidAndRevision() throws Exception {
        send("PUT", "/B1/summary", "{\"summary\":{\"a\":1}}", null, userToken);
        send("PUT", "/B1/summary", "{\"summary\":{\"a\":2}}", null, userToken);

        JsonNode json = mapper.readTree(send("GET", "/B1/summary", null, null, userToken).body());
        assertEquals(2, json.at("/summary/a").asInt());
        assertEquals("000", json.get("revision").asText());
    }

    @Test
    void getWithoutRevisionReturnsLatest() throws Exception {
        send("PUT", "/B2/summary", "{\"revision\":\"000\",\"summary\":{\"v\":0}}", null, userToken);
        send("PUT", "/B2/summary", "{\"revision\":\"001\",\"summary\":{\"v\":1}}", null, userToken);

        JsonNode latest = mapper.readTree(send("GET", "/B2/summary", null, null, userToken).body());
        JsonNode first = mapper.readTree(
                send("GET", "/B2/summary?revision=000", null, null, userToken).body());

        assertEquals(1, latest.at("/summary/v").asInt());
        assertEquals(0, first.at("/summary/v").asInt());
    }

    @Test
    void summaryAndPdfWritesRequireTheRightCredential() throws Exception {
        String body = "{\"summary\":{}}";

        assertEquals(401, send("PUT", "/B3/summary", body, null, null).statusCode());
        assertEquals(401, send("PUT", "/B3/summary", body, null, "garbage").statusCode());
        // 요약은 사용자 소유라 서비스 키로는 저장할 수 없습니다.
        assertEquals(401, send("PUT", "/B3/summary", body, SERVICE_KEY, null).statusCode());
        // PDF 업로드는 반대로 서비스 키만 허용합니다.
        assertEquals(401, send("POST", "/B3/documents?file_name=a.pdf", "x", null, userToken).statusCode());
        assertEquals(401, send("POST", "/B3/documents?file_name=a.pdf", "x", "wrong", null).statusCode());
    }

    @Test
    void readsRequireToken() throws Exception {
        assertEquals(401, send("GET", "/B4/summary", null, null, null).statusCode());
        assertEquals(401, send("GET", "/B4/summary", null, SERVICE_KEY, null).statusCode());
        assertEquals(401, send("GET", "/B4/documents", null, null, "garbage").statusCode());
        assertEquals(404, send("GET", "/B4/summary", null, null, userToken).statusCode());
    }

    @Test
    void ownerComesFromTokenAndSummariesAreIsolatedPerUser() throws Exception {
        // 본문에 사업자등록번호를 넣어도 무시되고 토큰의 사용자로 저장됩니다.
        send("PUT", "/S1/summary",
                "{\"business_registration_number\":\"9999999999\",\"summary\":{\"who\":\"me\"}}",
                null, userToken);
        send("PUT", "/S1/summary", "{\"summary\":{\"who\":\"other\"}}", null, otherUserToken);

        JsonNode mine = mapper.readTree(send("GET", "/S1/summary", null, null, userToken).body());
        JsonNode theirs = mapper.readTree(send("GET", "/S1/summary", null, null, otherUserToken).body());

        assertEquals("1234567890", mine.get("business_registration_number").asText());
        assertEquals("me", mine.at("/summary/who").asText());
        assertEquals("2222222222", theirs.get("business_registration_number").asText());
        assertEquals("other", theirs.at("/summary/who").asText());

        send("PUT", "/S2/summary", "{\"summary\":{}}", null, otherUserToken);
        assertEquals(404, send("GET", "/S2/summary", null, null, userToken).statusCode());
        assertEquals(1, mapper.readTree(send("GET", "", null, null, userToken).body()).size());
    }

    @Test
    void summaryResponseIncludesPdfLinks() throws Exception {
        sendBytes("/P1/documents?file_name=a.pdf&revision=000", PDF, SERVICE_KEY);
        sendBytes("/P1/documents?file_name=b.pdf&revision=001", PDF, SERVICE_KEY);
        send("PUT", "/P1/summary", "{\"revision\":\"000\",\"summary\":{}}", null, userToken);

        JsonNode json = mapper.readTree(send("GET", "/P1/summary", null, null, userToken).body());

        assertEquals(1, json.get("documents").size());
        assertEquals("a.pdf", json.at("/documents/0/file_name").asText());
        assertTrue(json.at("/documents/0/download_url").asText().startsWith("https://signed.example/bids/P1/000/"));
    }

    @Test
    void rejectsInvalidSummaryAndBidNo() throws Exception {
        assertEquals(400, send("PUT", "/B5/summary", "{\"summary\":[1]}", null, userToken).statusCode());
        assertEquals(400, send("PUT", "/B5/summary", "{}", null, userToken).statusCode());
        assertEquals(400, send("PUT", "/B5/summary",
                "{\"bid_no\":\"OTHER\",\"summary\":{}}", null, userToken).statusCode());
        assertEquals(400, send("PUT", "/a%20b/summary", "{\"summary\":{}}", null, userToken).statusCode());
    }

    @Test
    void uploadsPdfToStorageAndListsSignedUrl() throws Exception {
        HttpResponse<String> upload = sendBytes(
                "/R26BK1/documents?file_name=" + java.net.URLEncoder.encode("공고문 (1).pdf", StandardCharsets.UTF_8)
                        + "&source_url=https://www.g2b.go.kr/x&revision=000",
                PDF, SERVICE_KEY);
        assertEquals(201, upload.statusCode());
        String key = mapper.readTree(upload.body()).get("storage_key").asText();
        assertTrue(key.startsWith("bids/R26BK1/000/") && key.endsWith(".pdf"), key);
        assertTrue(storage.objects.containsKey(key));

        JsonNode list = mapper.readTree(send("GET", "/R26BK1/documents", null, null, userToken).body());
        assertEquals(1, list.size());
        assertEquals("공고문 (1).pdf", list.get(0).get("file_name").asText());
        assertEquals("https://www.g2b.go.kr/x", list.get(0).get("source_url").asText());
        assertEquals("https://signed.example/" + key, list.get(0).get("download_url").asText());
    }

    @Test
    void duplicateFileNameIsConflictAndNotPdfIsRejected() throws Exception {
        assertEquals(201, sendBytes("/B6/documents?file_name=a.pdf", PDF, SERVICE_KEY).statusCode());
        assertEquals(409, sendBytes("/B6/documents?file_name=a.pdf", PDF, SERVICE_KEY).statusCode());
        assertEquals(400, sendBytes("/B6/documents?file_name=b.pdf",
                "not a pdf".getBytes(StandardCharsets.UTF_8), SERVICE_KEY).statusCode());
        assertEquals(400, sendBytes("/B6/documents", PDF, SERVICE_KEY).statusCode());
        assertEquals(1, storage.objects.size());
    }

    @Test
    void listsSummariesWithPaging() throws Exception {
        send("PUT", "/L1/summary", "{\"summary\":{}}", null, userToken);
        send("PUT", "/L2/summary", "{\"summary\":{}}", null, userToken);

        JsonNode all = mapper.readTree(send("GET", "", null, null, userToken).body());
        JsonNode page = mapper.readTree(send("GET", "?limit=1&offset=1", null, null, userToken).body());

        assertEquals(2, all.size());
        assertEquals("L2", page.get(0).get("bid_no").asText());
        assertEquals(400, send("GET", "?limit=0", null, null, userToken).statusCode());
    }

    @Test
    void unknownPathAndMethodAreRejected() throws Exception {
        assertEquals(404, send("GET", "/B7/unknown", null, SERVICE_KEY, null).statusCode());
        assertEquals(405, send("DELETE", "/B7/summary", null, null, userToken).statusCode());
    }

    private HttpResponse<String> send(
            String method, String path, String body, String serviceKey, String token
    ) throws Exception {
        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(base + path))
                .method(method, body == null ? BodyPublishers.noBody() : BodyPublishers.ofString(body));
        if (serviceKey != null) {
            builder.header("X-Service-Key", serviceKey);
        }
        if (token != null) {
            builder.header("Authorization", "Bearer " + token);
        }
        return client.send(builder.build(), HttpResponse.BodyHandlers.ofString());
    }

    private HttpResponse<String> sendBytes(String path, byte[] body, String serviceKey) throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create(base + path))
                .header("X-Service-Key", serviceKey)
                .header("Content-Type", "application/pdf")
                .POST(BodyPublishers.ofByteArray(body))
                .build();
        return client.send(request, HttpResponse.BodyHandlers.ofString());
    }

    private static final class FakeStorage implements DocumentStorage {
        final Map<String, byte[]> objects = new ConcurrentHashMap<>();

        @Override
        public void upload(String storageKey, byte[] content, String contentType) {
            objects.put(storageKey, content);
        }

        @Override
        public String createSignedUrl(String storageKey, long expiresInSeconds) {
            return "https://signed.example/" + storageKey;
        }

        @Override
        public void delete(String storageKey) {
            objects.remove(storageKey);
        }
    }

    private static final class FakeSummaryRepository implements BidSummaryRepository {
        final Map<String, BidSummary> rows = new ConcurrentHashMap<>();

        @Override
        public BidSummary save(String brn, BidSummaryRequest r) {
            BidSummary saved = new BidSummary(brn, r.bidNo(), r.revision(), r.summary(), r.missing(),
                    r.needsReview(), r.handoff(), r.latencyMs(), Instant.now(), Instant.now());
            rows.put(brn + "/" + r.bidNo() + "/" + r.revision(), saved);
            return saved;
        }

        @Override
        public Optional<BidSummary> find(String brn, String bidNo, String revision) {
            return Optional.ofNullable(rows.get(brn + "/" + bidNo + "/" + revision));
        }

        @Override
        public Optional<BidSummary> findLatest(String brn, String bidNo) {
            return rows.values().stream()
                    .filter(s -> s.businessRegistrationNumber().equals(brn) && s.bidNo().equals(bidNo))
                    .max(Comparator.comparing(BidSummary::revision));
        }

        @Override
        public List<BidSummary> findAll(String brn, int limit, int offset) {
            return rows.values().stream()
                    .filter(s -> s.businessRegistrationNumber().equals(brn))
                    .sorted(Comparator.comparing(BidSummary::bidNo))
                    .skip(offset).limit(limit).toList();
        }
    }

    private static final class FakeDocumentRepository implements BidDocumentRepository {
        final List<BidDocument> rows = new ArrayList<>();

        @Override
        public boolean exists(String bidNo, String revision, String fileName) {
            return rows.stream().anyMatch(d -> d.bidNo().equals(bidNo)
                    && d.revision().equals(revision) && d.fileName().equals(fileName));
        }

        @Override
        public BidDocument save(String bidNo, String revision, String fileName,
                                String storageKey, long sizeBytes, String sourceUrl) {
            if (exists(bidNo, revision, fileName)) {
                throw new ConflictException("dup");
            }
            BidDocument doc = new BidDocument((long) rows.size() + 1, bidNo, revision,
                    fileName, storageKey, sizeBytes, sourceUrl, Instant.now());
            rows.add(doc);
            return doc;
        }

        @Override
        public List<BidDocument> findByBid(String bidNo, String revision) {
            return rows.stream().filter(d -> d.bidNo().equals(bidNo)
                    && (revision == null || d.revision().equals(revision))).toList();
        }
    }
}
