package workplace.security;

import com.auth0.jwt.JWT;
import com.auth0.jwt.JWTVerifier;
import com.auth0.jwt.algorithms.Algorithm;
import com.auth0.jwt.exceptions.JWTVerificationException;
import com.auth0.jwt.interfaces.DecodedJWT;
import workplace.domain.AuthenticatedUser;
import workplace.domain.User;
import workplace.exception.UnauthorizedException;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Date;

/** JWT 생성과 검증 책임을 인증·HTTP 코드에서 분리합니다. */
public final class JwtProvider {

    private final Algorithm algorithm;
    private final JWTVerifier verifier;
    private final String issuer;
    private final long expirationSeconds;

    public JwtProvider(String secret, String issuer, long expirationSeconds) {
        if (secret == null || secret.isBlank()) {
            throw new IllegalArgumentException("JWT secret must not be blank.");
        }
        this.algorithm = Algorithm.HMAC256(secret);
        this.issuer = issuer;
        this.expirationSeconds = expirationSeconds;
        this.verifier = JWT.require(algorithm).withIssuer(issuer).build();
    }

    /** 로그인한 사용자를 식별할 수 있는 Access Token을 생성합니다. */
    public String createAccessToken(User user) {
        Instant issuedAt = Instant.now();
        Instant expiresAt = issuedAt.plus(expirationSeconds, ChronoUnit.SECONDS);

        return JWT.create()
                .withIssuer(issuer)
                .withSubject(user.businessRegistrationNumber())
                .withClaim("corporate_name", user.corporateName())
                .withIssuedAt(Date.from(issuedAt))
                .withExpiresAt(Date.from(expiresAt))
                .sign(algorithm);
    }

    /** 서명·발급자·만료 시간을 검증하고 안전한 사용자 정보만 반환합니다. */
    public AuthenticatedUser verify(String token) {
        if (token == null || token.isBlank()) {
            throw new UnauthorizedException("인증 토큰이 없습니다.");
        }

        try {
            DecodedJWT decoded = verifier.verify(token);
            String businessRegistrationNumber = decoded.getSubject();
            String corporateName = decoded.getClaim("corporate_name").asString();

            if (businessRegistrationNumber == null
                    || !businessRegistrationNumber.matches("^[0-9]{10}$")
                    || corporateName == null
                    || corporateName.isBlank()) {
                throw new UnauthorizedException("인증 토큰에 사용자 정보가 없습니다.");
            }
            return new AuthenticatedUser(businessRegistrationNumber, corporateName);
        } catch (JWTVerificationException exception) {
            throw new UnauthorizedException("유효하지 않거나 만료된 인증 토큰입니다.");
        }
    }
}
