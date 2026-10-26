package workplace.exception;

/** DB 등 필수 인프라를 일시적으로 사용할 수 없을 때 발생합니다. */
public final class ServiceUnavailableException extends ApiException {

    public ServiceUnavailableException(String message, Throwable cause) {
        super(503, "SERVICE_UNAVAILABLE", message);
        initCause(cause);
    }
}
