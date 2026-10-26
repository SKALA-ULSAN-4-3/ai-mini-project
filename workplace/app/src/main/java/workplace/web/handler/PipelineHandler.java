package workplace.web.handler;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import workplace.domain.PipelineRequest;
import workplace.exception.ApiException;
import workplace.service.PipelineService;
import workplace.web.CurrentUserResolver;
import workplace.web.HttpResponses;
import workplace.web.RequestBodies;
import java.io.IOException;

/** HTTP 컨트롤러: 경로·메서드 검사, JWT 인증, 서비스 위임. */
public final class PipelineHandler implements HttpHandler {
    private final CurrentUserResolver users;
    private final PipelineService service;
    private final RequestBodies bodies;
    private final HttpResponses responses;

    public PipelineHandler(CurrentUserResolver users, PipelineService service,
                           RequestBodies bodies, HttpResponses responses) {
        this.users = users;
        this.service = service;
        this.bodies = bodies;
        this.responses = responses;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        boolean list = path.equals("/api/me/pipeline");
        boolean approval = path.equals("/api/me/approvals");
        if (!list && !approval && !path.equals("/api/me/selections")) {
            throw new ApiException(404, "RESOURCE_NOT_FOUND", "존재하지 않는 경로입니다.");
        }
        if (!(list ? "GET" : "POST").equals(exchange.getRequestMethod())) {
            throw new ApiException(405, "METHOD_NOT_ALLOWED", "허용되지 않는 HTTP 메서드입니다.");
        }
        // 사용자 격리: 본문의 사용자 정보 대신 JWT 사용.
        String user = users.resolve(exchange).businessRegistrationNumber();
        if (list) {
            responses.json(exchange, 200, service.list(user));
        } else {
            responses.json(exchange, 200, service.save(user,
                    bodies.json(exchange, PipelineRequest.class), approval));
        }
    }
}
