package workplace.web.handler;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import workplace.web.HttpMethods;
import workplace.web.HttpResponses;

import java.io.IOException;
import java.util.Map;

/**
 * 프로세스 자체가 HTTP 요청을 처리할 수 있는지 확인합니다.
 *
 * <p>DB 장애 때문에 정상적인 백엔드 프로세스까지 Kubernetes가 반복해서
 * 재시작하지 않도록, liveness 검사에서는 외부 의존성을 확인하지 않습니다.</p>
 */
public final class LivenessHandler implements HttpHandler {

    private final HttpResponses responses;

    public LivenessHandler(HttpResponses responses) {
        this.responses = responses;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        HttpMethods.require(exchange, "GET");
        responses.json(exchange, 200, Map.of(
                "status", "ok",
                "api", "alive"
        ));
    }
}
