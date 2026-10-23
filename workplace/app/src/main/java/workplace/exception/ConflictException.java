package workplace.exception;

/** 현재 저장 상태와 요청이 충돌할 때 발생합니다. */
public final class ConflictException extends ApiException {

    public ConflictException(String message) {
        super(409, "RESOURCE_CONFLICT", message);
    }
}
