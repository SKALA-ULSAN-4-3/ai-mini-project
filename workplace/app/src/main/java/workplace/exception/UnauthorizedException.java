package workplace.exception;

/** 로그인 정보가 없거나 JWT가 유효하지 않을 때 발생합니다. */
public final class UnauthorizedException extends ApiException {

    public UnauthorizedException(String message) {
        super(401, "UNAUTHORIZED", message);
    }
}
