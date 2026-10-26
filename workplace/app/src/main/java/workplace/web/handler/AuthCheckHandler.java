package workplace.web.handler;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import workplace.domain.AuthenticatedUser;
import workplace.domain.User;
import workplace.service.AuthService;
import workplace.web.CurrentUserResolver;
import workplace.web.HttpMethods;
import workplace.web.HttpResponses;

import java.io.IOException;
import java.util.Map;

/** Authorization 헤더의 Bearer JWT가 유효한지 확인합니다. */
public final class AuthCheckHandler implements HttpHandler {

    private final CurrentUserResolver currentUserResolver;
    private final AuthService authService;
    private final HttpResponses responses;

    public AuthCheckHandler(
            CurrentUserResolver currentUserResolver,
            AuthService authService,
            HttpResponses responses
    ) {
        this.currentUserResolver = currentUserResolver;
        this.authService = authService;
        this.responses = responses;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        HttpMethods.require(exchange, "GET");
        AuthenticatedUser authenticatedUser = currentUserResolver.resolve(exchange);
        User user = authService.getAuthenticatedUser(
                authenticatedUser.businessRegistrationNumber()
        );

        responses.json(exchange, 200, Map.of(
                "ok", true,
                "business_registration_number", user.businessRegistrationNumber(),
                "corporate_name", user.corporateName(),
                "head_office_address", user.headOfficeAddress(),
                "business_type", user.businessType(),
                "business_item", user.businessItem()
        ));
    }
}
