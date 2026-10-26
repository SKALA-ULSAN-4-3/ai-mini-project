package workplace.web.handler;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import workplace.domain.AuthenticatedUser;
import workplace.domain.CompanyProfile;
import workplace.domain.CompanyProfileRequest;
import workplace.exception.ApiException;
import workplace.service.CompanyProfileService;
import workplace.web.CurrentUserResolver;
import workplace.web.HttpResponses;
import workplace.web.RequestBodies;

import java.io.IOException;

/** 현재 로그인 사용자의 회사 프로필 조회·저장 API입니다. */
public final class ProfileHandler implements HttpHandler {

    private final CurrentUserResolver currentUserResolver;
    private final CompanyProfileService profileService;
    private final RequestBodies requestBodies;
    private final HttpResponses responses;

    public ProfileHandler(
            CurrentUserResolver currentUserResolver,
            CompanyProfileService profileService,
            RequestBodies requestBodies,
            HttpResponses responses
    ) {
        this.currentUserResolver = currentUserResolver;
        this.profileService = profileService;
        this.requestBodies = requestBodies;
        this.responses = responses;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        AuthenticatedUser user = currentUserResolver.resolve(exchange);

        switch (exchange.getRequestMethod().toUpperCase()) {
            case "GET" -> get(exchange, user);
            case "PUT" -> save(exchange, user);
            default -> throw new ApiException(
                    405,
                    "METHOD_NOT_ALLOWED",
                    "허용되지 않은 HTTP 메서드입니다."
            );
        }
    }

    private void get(HttpExchange exchange, AuthenticatedUser user) throws IOException {
        CompanyProfile profile = profileService.get(user.businessRegistrationNumber());
        responses.json(exchange, 200, profile);
    }

    private void save(HttpExchange exchange, AuthenticatedUser user) throws IOException {
        CompanyProfileRequest request = requestBodies.json(
                exchange,
                CompanyProfileRequest.class
        );
        CompanyProfile profile = profileService.save(
                user.businessRegistrationNumber(),
                request
        );
        responses.json(exchange, 200, profile);
    }
}
