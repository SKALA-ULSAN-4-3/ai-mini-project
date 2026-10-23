package workplace.web.handler;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import workplace.exception.ServiceUnavailableException;
import workplace.repository.ConnectionFactory;
import workplace.web.HttpMethods;
import workplace.web.HttpResponses;

import java.io.IOException;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.Map;

/** 서버가 트래픽을 받을 준비가 되었는지 MariaDB 연결까지 확인합니다. */
public final class HealthHandler implements HttpHandler {

    private final ConnectionFactory connectionFactory;
    private final HttpResponses responses;

    public HealthHandler(ConnectionFactory connectionFactory, HttpResponses responses) {
        this.connectionFactory = connectionFactory;
        this.responses = responses;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        HttpMethods.require(exchange, "GET");

        try (Connection connection = connectionFactory.open()) {
            if (!connection.isValid(2)) {
                throw new ServiceUnavailableException(
                        "데이터베이스 연결이 준비되지 않았습니다.",
                        null
                );
            }
        } catch (SQLException exception) {
            throw new ServiceUnavailableException(
                    "데이터베이스 연결이 준비되지 않았습니다.",
                    exception
            );
        }

        responses.json(exchange, 200, Map.of(
                "status", "ok",
                "api", "ready",
                "database", "ready"
        ));
    }
}
