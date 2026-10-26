package workplace.web;

import com.sun.net.httpserver.HttpExchange;
import workplace.domain.AuthenticatedUser;
import workplace.security.JwtProvider;

/** Authorization 헤더의 Bearer JWT를 검증해 현재 사용자를 반환합니다. */
public final class CurrentUserResolver {

    private final JwtProvider jwtProvider;

    public CurrentUserResolver(JwtProvider jwtProvider) {
        this.jwtProvider = jwtProvider;
    }

    public AuthenticatedUser resolve(HttpExchange exchange) {
        String authorization = exchange.getRequestHeaders().getFirst("Authorization");
        if (authorization == null
                || !authorization.regionMatches(true, 0, "Bearer ", 0, 7)) {
            return jwtProvider.verify(null);
        }

        String token = authorization.substring(7).trim();
        return jwtProvider.verify(token);
    }
}
