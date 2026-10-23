package workplace.domain;

/** 로그인 성공 시 클라이언트가 받는 Access Token 응답입니다. */
public record TokenResponse(
        String accessToken,
        String tokenType,
        long expiresIn
) {
}
