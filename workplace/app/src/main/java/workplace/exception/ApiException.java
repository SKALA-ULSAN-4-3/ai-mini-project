package workplace.exception;

/** 클라이언트에게 안전하게 전달할 수 있는 공통 API 예외입니다. */
public class ApiException extends RuntimeException {

    private final int statusCode;
    private final String code;

    public ApiException(int statusCode, String code, String message) {
        super(message);
        this.statusCode = statusCode;
        this.code = code;
    }

    public int statusCode() {
        return statusCode;
    }

    public String code() {
        return code;
    }
}
