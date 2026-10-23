package workplace.exception;

/** 요청 값이 업무 규칙을 만족하지 않을 때 발생합니다. */
public final class ValidationException extends ApiException {

    public ValidationException(String message) {
        super(400, "INVALID_REQUEST", message);
    }
}
