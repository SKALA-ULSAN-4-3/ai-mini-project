package workplace.web.handler;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import workplace.domain.AuthenticatedUser;
import workplace.domain.User;
import workplace.exception.UnauthorizedException;
import workplace.repository.UserRepository;
import workplace.web.CurrentUserResolver;
import workplace.web.HttpMethods;
import workplace.web.HttpResponses;

import java.io.IOException;
import java.util.Map;

/** Authorization 헤더의 Bearer JWT가 유효한지 확인합니다. */
public final class AuthCheckHandler implements HttpHandler {

    private final CurrentUserResolver currentUserResolver;
    private final UserRepository userRepository;
    private final HttpResponses responses;

    public AuthCheckHandler(
            CurrentUserResolver currentUserResolver,
            UserRepository userRepository,
            HttpResponses responses
    ) {
        this.currentUserResolver = currentUserResolver;
        this.userRepository = userRepository;
        this.responses = responses;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        HttpMethods.require(exchange, "GET");
        AuthenticatedUser user = currentUserResolver.resolve(exchange);
        User details = userRepository.findByBusinessRegistrationNumber(
                user.businessRegistrationNumber()).orElseThrow(
                () -> new UnauthorizedException("등록된 사용자 정보를 찾을 수 없습니다."));

        responses.json(exchange, 200, Map.of(
                "ok", true,
                "business_registration_number", details.businessRegistrationNumber(),
                "corporate_name", details.corporateName(),
                "head_office_address", details.headOfficeAddress(),
                "business_type", details.businessType(),
                "business_item", details.businessItem()
        ));
    }
}
