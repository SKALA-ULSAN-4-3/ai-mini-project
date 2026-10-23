package workplace.web;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;

import java.io.IOException;
import java.util.Set;

/** 허용된 프론트엔드 출처와 Bearer 인증용 CORS 사전 요청을 처리합니다. */
public final class CorsHandler implements HttpHandler {

    private final HttpHandler delegate;
    private final HttpResponses responses;
    private final Set<String> allowedOrigins;

    public CorsHandler(
            HttpHandler delegate,
            HttpResponses responses,
            Set<String> allowedOrigins
    ) {
        this.delegate = delegate;
        this.responses = responses;
        this.allowedOrigins = allowedOrigins;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        String origin = exchange.getRequestHeaders().getFirst("Origin");
        if (origin != null && allowedOrigins.contains(origin)) {
            exchange.getResponseHeaders().set("Access-Control-Allow-Origin", origin);
            exchange.getResponseHeaders().set("Vary", "Origin");
        }

        if ("OPTIONS".equalsIgnoreCase(exchange.getRequestMethod())) {
            exchange.getResponseHeaders().set(
                    "Access-Control-Allow-Methods",
                    "GET, POST, PUT, DELETE, OPTIONS"
            );
            exchange.getResponseHeaders().set(
                    "Access-Control-Allow-Headers",
                    "Authorization, Content-Type, X-Request-ID"
            );
            responses.empty(exchange, 204);
            return;
        }
        delegate.handle(exchange);
    }
}
