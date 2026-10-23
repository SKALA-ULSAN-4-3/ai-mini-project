package workplace.exception;

/** 요청한 프로필 등의 리소스가 존재하지 않을 때 발생합니다. */
public final class NotFoundException extends ApiException {

    public NotFoundException(String message) {
        super(404, "RESOURCE_NOT_FOUND", message);
    }
}
