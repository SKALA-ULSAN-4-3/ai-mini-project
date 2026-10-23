package workplace.web.handler;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import workplace.exception.NotFoundException;
import workplace.web.HttpMethods;
import workplace.web.HttpResponses;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/** 로그인·회원가입 데모 화면의 정적 리소스를 제공합니다. */
public final class StaticResourceHandler implements HttpHandler {

    private final String resourcePath;
    private final String contentType;
    private final HttpResponses responses;

    public StaticResourceHandler(
            String resourcePath,
            String contentType,
            HttpResponses responses
    ) {
        this.resourcePath = resourcePath;
        this.contentType = contentType;
        this.responses = responses;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        HttpMethods.require(exchange, "GET");

        try (InputStream input = getClass().getClassLoader().getResourceAsStream(resourcePath)) {
            if (input == null) {
                throw new NotFoundException("요청한 정적 파일을 찾을 수 없습니다.");
            }
            String content = new String(input.readAllBytes(), StandardCharsets.UTF_8);
            responses.text(exchange, 200, contentType, content);
        }
    }
}
