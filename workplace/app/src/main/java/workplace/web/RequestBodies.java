package workplace.web;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import workplace.exception.ValidationException;

import java.io.IOException;

/** JSON 요청 본문 파싱을 담당합니다. */
public final class RequestBodies {

    private final ObjectMapper objectMapper;

    public RequestBodies(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public <T> T json(HttpExchange exchange, Class<T> type) {
        try {
            return objectMapper.readValue(exchange.getRequestBody(), type);
        } catch (IOException exception) {
            throw new ValidationException("JSON 요청 본문을 읽을 수 없습니다.");
        }
    }

}
