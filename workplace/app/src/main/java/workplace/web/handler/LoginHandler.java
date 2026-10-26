package workplace.web.handler;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import workplace.config.AppConfig;
import workplace.domain.LoginRequest;
import workplace.domain.TokenResponse;
import workplace.domain.User;
import workplace.security.JwtProvider;
import workplace.service.AuthService;
import workplace.web.HttpMethods;
import workplace.web.HttpResponses;
import workplace.web.RequestBodies;

import java.io.IOException;

/** 로그인 검증 후 클라이언트가 사용할 Bearer JWT를 JSON으로 발급합니다. */
public final class LoginHandler implements HttpHandler {

    private final AuthService authService;
    private final JwtProvider jwtProvider;
    private final RequestBodies requestBodies;
    private final HttpResponses responses;
    private final AppConfig config;

    public LoginHandler(
            AuthService authService,
            JwtProvider jwtProvider,
            RequestBodies requestBodies,
            HttpResponses responses,
            AppConfig config
    ) {
        this.authService = authService;
        this.jwtProvider = jwtProvider;
        this.requestBodies = requestBodies;
        this.responses = responses;
        this.config = config;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        HttpMethods.require(exchange, "POST");

        LoginRequest request = requestBodies.json(exchange, LoginRequest.class);
        User user = authService.login(request);
        String accessToken = jwtProvider.createAccessToken(user);

        responses.json(exchange, 200, new TokenResponse(
                accessToken,
                "Bearer",
                config.jwtExpirationSeconds()
        ));
    }
}
