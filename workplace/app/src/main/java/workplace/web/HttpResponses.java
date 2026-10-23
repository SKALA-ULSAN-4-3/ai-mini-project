package workplace.web;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/** HTTP 응답 생성과 스트림 종료 방식을 통일합니다. */
public final class HttpResponses {

    private final ObjectMapper objectMapper;

    public HttpResponses(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public void json(HttpExchange exchange, int statusCode, Object body) throws IOException {
        byte[] bytes = objectMapper.writeValueAsBytes(body);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        write(exchange, statusCode, bytes);
    }

    public void text(
            HttpExchange exchange,
            int statusCode,
            String contentType,
            String body
    ) throws IOException {
        exchange.getResponseHeaders().set("Content-Type", contentType);
        write(exchange, statusCode, body.getBytes(StandardCharsets.UTF_8));
    }

    public void empty(HttpExchange exchange, int statusCode) throws IOException {
        exchange.sendResponseHeaders(statusCode, -1);
        exchange.close();
    }

    public void redirect(HttpExchange exchange, String location) throws IOException {
        exchange.getResponseHeaders().set("Location", location);
        empty(exchange, 302);
    }

    private void write(HttpExchange exchange, int statusCode, byte[] bytes) throws IOException {
        exchange.sendResponseHeaders(statusCode, bytes.length);
        try (OutputStream output = exchange.getResponseBody()) {
            output.write(bytes);
        }
    }
}
