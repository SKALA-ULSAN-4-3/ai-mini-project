package workplace.security;

import org.junit.jupiter.api.Test;
import workplace.domain.AuthenticatedUser;
import workplace.domain.User;
import workplace.exception.UnauthorizedException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class JwtProviderTest {

    private static final String SECRET =
            "test-secret-that-is-long-enough-for-hmac-sha256";

    @Test
    void createsAndVerifiesAccessToken() {
        JwtProvider provider = new JwtProvider(SECRET, "simple-auth-server", 3600);
        User user = user();

        String token = provider.createAccessToken(user);
        AuthenticatedUser authenticatedUser = provider.verify(token);

        assertEquals(
                "1234567890",
                authenticatedUser.businessRegistrationNumber()
        );
        assertEquals("테스트 주식회사", authenticatedUser.corporateName());
    }

    @Test
    void rejectsExpiredToken() {
        JwtProvider provider = new JwtProvider(SECRET, "simple-auth-server", -1);
        User user = user();

        String token = provider.createAccessToken(user);

        assertThrows(UnauthorizedException.class, () -> provider.verify(token));
    }

    private User user() {
        return new User(
                "1234567890",
                "unused-password-hash",
                "테스트 주식회사",
                "울산광역시 남구",
                "정보통신업",
                "소프트웨어 개발 및 공급업",
                "부"
        );
    }
}
