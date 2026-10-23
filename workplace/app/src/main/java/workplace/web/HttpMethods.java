package workplace.web;

import com.sun.net.httpserver.HttpExchange;
import workplace.exception.ApiException;

/** 엔드포인트별 허용 HTTP 메서드를 일관되게 검증합니다. */
public final class HttpMethods {

    private HttpMethods() {
    }

    public static void require(HttpExchange exchange, String expectedMethod) {
        if (!expectedMethod.equalsIgnoreCase(exchange.getRequestMethod())) {
            throw new ApiException(405, "METHOD_NOT_ALLOWED", "허용되지 않은 HTTP 메서드입니다.");
        }
    }
}
