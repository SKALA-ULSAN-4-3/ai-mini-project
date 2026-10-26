package workplace.web.handler;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import workplace.web.HttpMethods;
import workplace.web.HttpResponses;

import java.io.IOException;

/** GET 요청을 지정한 화면으로 이동시킵니다. */
public final class RedirectHandler implements HttpHandler {

    private final String location;
    private final HttpResponses responses;

    public RedirectHandler(String location, HttpResponses responses) {
        this.location = location;
        this.responses = responses;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        HttpMethods.require(exchange, "GET");
        responses.redirect(exchange, location);
    }
}
