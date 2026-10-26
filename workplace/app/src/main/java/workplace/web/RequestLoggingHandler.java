package workplace.web;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;

import java.io.IOException;
import java.util.UUID;
import java.util.logging.Logger;

/** 민감한 본문과 JWT를 제외한 요청 메타데이터만 기록합니다. */
public final class RequestLoggingHandler implements HttpHandler {

    public static final String REQUEST_ID_ATTRIBUTE = "requestId";

    private static final Logger LOGGER = Logger.getLogger(RequestLoggingHandler.class.getName());

    private final HttpHandler delegate;

    public RequestLoggingHandler(HttpHandler delegate) {
        this.delegate = delegate;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        String requestId = requestId(exchange);
        exchange.setAttribute(REQUEST_ID_ATTRIBUTE, requestId);
        exchange.getResponseHeaders().set("X-Request-ID", requestId);

        long startedAt = System.nanoTime();
        try {
            delegate.handle(exchange);
        } finally {
            long durationMillis = (System.nanoTime() - startedAt) / 1_000_000L;
            LOGGER.info(() -> String.format(
                    "request_id=%s method=%s path=%s status=%d duration_ms=%d",
                    requestId,
                    exchange.getRequestMethod(),
                    exchange.getRequestURI().getPath(),
                    exchange.getResponseCode(),
                    durationMillis
            ));
        }
    }

    private String requestId(HttpExchange exchange) {
        String provided = exchange.getRequestHeaders().getFirst("X-Request-ID");
        return provided == null || provided.isBlank()
                ? UUID.randomUUID().toString()
                : provided.trim();
    }
}
