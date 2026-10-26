package workplace.web.handler;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import workplace.domain.AuthenticatedUser;
import workplace.domain.RfpCacheRequest;
import workplace.domain.SearchCacheRequest;
import workplace.exception.ApiException;
import workplace.service.BidCacheService;
import workplace.web.CurrentUserResolver;
import workplace.web.HttpMethods;
import workplace.web.HttpResponses;
import workplace.web.RequestBodies;
import workplace.web.ServiceKeyAuthenticator;

import java.io.IOException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;

/** 데이터 파이프라인·RAG가 사용하는 내부 캐시 API를 제공합니다. */
public final class BidCacheHandler implements HttpHandler {

    private static final String BASE_PATH = "/api/cache";

    private final CurrentUserResolver currentUserResolver;
    private final ServiceKeyAuthenticator serviceKeys;
    private final BidCacheService cacheService;
    private final RequestBodies requestBodies;
    private final HttpResponses responses;

    public BidCacheHandler(
            CurrentUserResolver currentUserResolver,
            ServiceKeyAuthenticator serviceKeys,
            BidCacheService cacheService,
            RequestBodies requestBodies,
            HttpResponses responses
    ) {
        this.currentUserResolver = currentUserResolver;
        this.serviceKeys = serviceKeys;
        this.cacheService = cacheService;
        this.requestBodies = requestBodies;
        this.responses = responses;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        String[] segments = segments(exchange);

        if (segments.length == 2
                && "search".equals(segments[0])
                && "lookup".equals(segments[1])) {
            lookupSearch(exchange);
            return;
        }
        if (segments.length == 1 && "search".equals(segments[0])) {
            saveSearch(exchange);
            return;
        }
        if (segments.length == 2 && "rfp".equals(segments[0])) {
            handleRfp(exchange, segments[1]);
            return;
        }
        throw new ApiException(404, "RESOURCE_NOT_FOUND", "존재하지 않는 캐시 경로입니다.");
    }

    private void lookupSearch(HttpExchange exchange) throws IOException {
        HttpMethods.require(exchange, "POST");
        serviceKeys.require(exchange);
        AuthenticatedUser user = currentUserResolver.resolve(exchange);
        SearchCacheRequest request = requestBodies.json(exchange, SearchCacheRequest.class);
        responses.json(exchange, 200, cacheService.findSearch(
                user.businessRegistrationNumber(),
                request
        ));
    }

    private void saveSearch(HttpExchange exchange) throws IOException {
        HttpMethods.require(exchange, "PUT");
        serviceKeys.require(exchange);
        AuthenticatedUser user = currentUserResolver.resolve(exchange);
        SearchCacheRequest request = requestBodies.json(exchange, SearchCacheRequest.class);
        responses.json(exchange, 200, cacheService.saveSearch(
                user.businessRegistrationNumber(),
                request
        ));
    }

    private void handleRfp(HttpExchange exchange, String encodedBidNo) throws IOException {
        serviceKeys.require(exchange);
        String bidNo = URLDecoder.decode(encodedBidNo, StandardCharsets.UTF_8);
        if ("GET".equalsIgnoreCase(exchange.getRequestMethod())) {
            responses.json(exchange, 200, cacheService.findRfp(
                    bidNo,
                    revision(exchange)
            ));
            return;
        }
        if ("PUT".equalsIgnoreCase(exchange.getRequestMethod())) {
            RfpCacheRequest request = requestBodies.json(exchange, RfpCacheRequest.class);
            responses.json(exchange, 200, cacheService.saveRfp(bidNo, request));
            return;
        }
        throw new ApiException(405, "METHOD_NOT_ALLOWED", "허용되지 않은 HTTP 메서드입니다.");
    }

    private String[] segments(HttpExchange exchange) {
        String path = exchange.getRequestURI().getPath();
        String rest = path.length() > BASE_PATH.length()
                ? path.substring(BASE_PATH.length())
                : "";
        String trimmed = rest.replaceAll("^/+|/+$", "");
        return trimmed.isEmpty() ? new String[0] : trimmed.split("/");
    }

    private String revision(HttpExchange exchange) {
        String raw = exchange.getRequestURI().getRawQuery();
        if (raw == null || raw.isBlank()) {
            return null;
        }
        for (String pair : raw.split("&")) {
            int equals = pair.indexOf('=');
            String key = equals < 0 ? pair : pair.substring(0, equals);
            if ("revision".equals(URLDecoder.decode(key, StandardCharsets.UTF_8))) {
                String value = equals < 0 ? "" : pair.substring(equals + 1);
                return URLDecoder.decode(value, StandardCharsets.UTF_8);
            }
        }
        return null;
    }
}
