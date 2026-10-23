package workplace.web.handler;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import workplace.domain.AuthenticatedUser;
import workplace.domain.BidDocumentView;
import workplace.domain.BidSummary;
import workplace.domain.BidSummaryRequest;
import workplace.domain.BidSummaryView;
import workplace.exception.ApiException;
import workplace.exception.ValidationException;
import workplace.service.BidDocumentService;
import workplace.service.BidSummaryService;
import workplace.web.CurrentUserResolver;
import workplace.web.HttpResponses;
import workplace.web.RequestBodies;
import workplace.web.ServiceKeyAuthenticator;

import java.io.IOException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 공고 요약(DB)과 원본 PDF(Storage + DB 메타데이터)를 다루는 /api/bids API입니다.
 *
 * <p>요약은 로그인한 사업자 소유입니다. 사업자등록번호는 요청에 담지 않고 JWT에서
 * 서버가 채우며, 본인 요약만 조회·저장할 수 있습니다. 공고 원본 PDF는 모든 사용자가
 * 함께 보는 자료라 데이터 파이프라인이 서비스 키로 올립니다.</p>
 *
 * <ul>
 *   <li>GET  /api/bids — 내 요약 목록 (JWT)</li>
 *   <li>GET  /api/bids/{bid_no}/summary — 내 요약과 PDF 링크, revision 생략 시 최신 차수 (JWT)</li>
 *   <li>PUT  /api/bids/{bid_no}/summary — 내 요약 저장·덮어쓰기 (JWT)</li>
 *   <li>GET  /api/bids/{bid_no}/documents — PDF 목록과 임시 다운로드 주소 (JWT 또는 서비스 키)</li>
 *   <li>POST /api/bids/{bid_no}/documents — PDF 업로드, 본문은 PDF 바이너리 (서비스 키)</li>
 * </ul>
 */
public final class BidHandler implements HttpHandler {

    private static final String BASE_PATH = "/api/bids";
    private static final int DEFAULT_PAGE_SIZE = 50;

    private final CurrentUserResolver currentUserResolver;
    private final ServiceKeyAuthenticator serviceKeys;
    private final BidSummaryService summaryService;
    private final BidDocumentService documentService;
    private final RequestBodies requestBodies;
    private final HttpResponses responses;

    public BidHandler(
            CurrentUserResolver currentUserResolver,
            ServiceKeyAuthenticator serviceKeys,
            BidSummaryService summaryService,
            BidDocumentService documentService,
            RequestBodies requestBodies,
            HttpResponses responses
    ) {
        this.currentUserResolver = currentUserResolver;
        this.serviceKeys = serviceKeys;
        this.summaryService = summaryService;
        this.documentService = documentService;
        this.requestBodies = requestBodies;
        this.responses = responses;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        String[] segments = segments(exchange);
        String method = exchange.getRequestMethod().toUpperCase();

        if (segments.length == 0) {
            if (!"GET".equals(method)) {
                throw methodNotAllowed();
            }
            list(exchange, currentUserResolver.resolve(exchange));
            return;
        }

        if (segments.length == 2 && "summary".equals(segments[1])) {
            switch (method) {
                case "GET" -> getSummary(
                        exchange,
                        currentUserResolver.resolve(exchange),
                        segments[0]
                );
                case "PUT" -> saveSummary(
                        exchange,
                        currentUserResolver.resolve(exchange),
                        segments[0]
                );
                default -> throw methodNotAllowed();
            }
            return;
        }

        if (segments.length == 2 && "documents".equals(segments[1])) {
            switch (method) {
                case "GET" -> {
                    requireReader(exchange);
                    listDocuments(exchange, segments[0]);
                }
                case "POST" -> {
                    serviceKeys.require(exchange);
                    uploadDocument(exchange, segments[0]);
                }
                default -> throw methodNotAllowed();
            }
            return;
        }

        throw new ApiException(404, "RESOURCE_NOT_FOUND", "존재하지 않는 경로입니다.");
    }

    private void list(HttpExchange exchange, AuthenticatedUser user) throws IOException {
        Map<String, String> query = query(exchange);
        List<BidSummary> summaries = summaryService.list(
                user.businessRegistrationNumber(),
                intParam(query, "limit", DEFAULT_PAGE_SIZE),
                intParam(query, "offset", 0)
        );
        responses.json(exchange, 200, summaries);
    }

    private void getSummary(
            HttpExchange exchange,
            AuthenticatedUser user,
            String bidNo
    ) throws IOException {
        BidSummary summary = summaryService.get(
                user.businessRegistrationNumber(),
                bidNo,
                query(exchange).get("revision")
        );
        responses.json(exchange, 200, BidSummaryView.of(
                summary,
                documentService.linksOrEmpty(summary.bidNo(), summary.revision())
        ));
    }

    private void saveSummary(
            HttpExchange exchange,
            AuthenticatedUser user,
            String bidNo
    ) throws IOException {
        BidSummaryRequest request = requestBodies.json(exchange, BidSummaryRequest.class);
        responses.json(exchange, 200, summaryService.save(
                user.businessRegistrationNumber(),
                bidNo,
                request
        ));
    }

    private void listDocuments(HttpExchange exchange, String bidNo) throws IOException {
        List<BidDocumentView> documents =
                documentService.list(bidNo, query(exchange).get("revision"));
        responses.json(exchange, 200, documents);
    }

    private void uploadDocument(HttpExchange exchange, String bidNo) throws IOException {
        Map<String, String> query = query(exchange);
        byte[] content = exchange.getRequestBody()
                .readNBytes((int) BidDocumentService.MAX_PDF_BYTES + 1);

        BidDocumentView document = documentService.upload(
                bidNo,
                query.get("revision"),
                query.get("file_name"),
                query.get("source_url"),
                content
        );
        responses.json(exchange, 201, document);
    }

    /** PDF 조회용입니다. 서비스 키가 맞으면 통과하고, 아니면 로그인 JWT를 검증합니다. */
    private void requireReader(HttpExchange exchange) {
        if (!serviceKeys.matches(exchange)) {
            currentUserResolver.resolve(exchange);
        }
    }

    private String[] segments(HttpExchange exchange) {
        String path = exchange.getRequestURI().getPath();
        String rest = path.length() > BASE_PATH.length()
                ? path.substring(BASE_PATH.length())
                : "";
        String trimmed = rest.replaceAll("^/+|/+$", "");
        return trimmed.isEmpty() ? new String[0] : trimmed.split("/");
    }

    private Map<String, String> query(HttpExchange exchange) {
        Map<String, String> result = new HashMap<>();
        String raw = exchange.getRequestURI().getRawQuery();
        if (raw == null || raw.isBlank()) {
            return result;
        }
        for (String pair : raw.split("&")) {
            int equals = pair.indexOf('=');
            String key = equals < 0 ? pair : pair.substring(0, equals);
            String value = equals < 0 ? "" : pair.substring(equals + 1);
            result.put(
                    URLDecoder.decode(key, StandardCharsets.UTF_8),
                    URLDecoder.decode(value, StandardCharsets.UTF_8)
            );
        }
        return result;
    }

    private int intParam(Map<String, String> query, String name, int defaultValue) {
        String value = query.get(name);
        if (value == null || value.isBlank()) {
            return defaultValue;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException exception) {
            throw new ValidationException(name + "은(는) 정수여야 합니다.");
        }
    }

    private ApiException methodNotAllowed() {
        return new ApiException(405, "METHOD_NOT_ALLOWED", "허용되지 않은 HTTP 메서드입니다.");
    }
}
