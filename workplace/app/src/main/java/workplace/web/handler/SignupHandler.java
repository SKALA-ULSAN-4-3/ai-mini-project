package workplace.web.handler;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import workplace.domain.SignupRequest;
import workplace.domain.User;
import workplace.service.AuthService;
import workplace.web.HttpMethods;
import workplace.web.HttpResponses;
import workplace.web.RequestBodies;

import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;

/** 회원가입 요청을 검증하고 사용자 저장을 AuthService에 위임합니다. */
public final class SignupHandler implements HttpHandler {

    private final AuthService authService;
    private final RequestBodies requestBodies;
    private final HttpResponses responses;

    public SignupHandler(
            AuthService authService,
            RequestBodies requestBodies,
            HttpResponses responses
    ) {
        this.authService = authService;
        this.requestBodies = requestBodies;
        this.responses = responses;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        HttpMethods.require(exchange, "POST");
        SignupRequest request = requestBodies.json(exchange, SignupRequest.class);
        User user = authService.signUp(request);

        // 응답에 비밀번호나 비밀번호 해시는 절대 포함하지 않습니다.
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("business_registration_number", user.businessRegistrationNumber());
        body.put("corporate_name", user.corporateName());
        responses.json(exchange, 201, body);
    }
}
