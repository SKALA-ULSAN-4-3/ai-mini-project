package workplace.web;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import workplace.exception.ApiException;

import java.io.IOException;
import java.util.Map;
import java.util.logging.Level;
import java.util.logging.Logger;

/** 모든 엔드포인트 예외를 공통 JSON 오류 형식으로 변환합니다. */
public final class ErrorHandlingHandler implements HttpHandler {

    private static final Logger LOGGER = Logger.getLogger(ErrorHandlingHandler.class.getName());

    private final HttpHandler delegate;
    private final HttpResponses responses;

    public ErrorHandlingHandler(HttpHandler delegate, HttpResponses responses) {
        this.delegate = delegate;
        this.responses = responses;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        try {
            delegate.handle(exchange);
        } catch (ApiException exception) {
            responses.json(exchange, exception.statusCode(), Map.of(
                    "code", exception.code(),
                    "message", exception.getMessage(),
                    "request_id", requestId(exchange)
            ));
        } catch (Exception exception) {
            LOGGER.log(
                    Level.SEVERE,
                    "처리되지 않은 서버 오류. request_id=" + requestId(exchange),
                    exception
            );
            responses.json(exchange, 500, Map.of(
                    "code", "INTERNAL_SERVER_ERROR",
                    "message", "서버 내부 오류가 발생했습니다.",
                    "request_id", requestId(exchange)
            ));
        }
    }

    private String requestId(HttpExchange exchange) {
        Object requestId = exchange.getAttribute(RequestLoggingHandler.REQUEST_ID_ATTRIBUTE);
        return requestId == null ? "unknown" : requestId.toString();
    }
}
