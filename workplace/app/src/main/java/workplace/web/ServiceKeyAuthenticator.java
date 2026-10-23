package workplace.web;

import com.sun.net.httpserver.HttpExchange;
import workplace.exception.ServiceUnavailableException;
import workplace.exception.UnauthorizedException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/**
 * 데이터 파이프라인·RAG 서비스처럼 사용자 로그인 없이 호출하는 서버 간 요청을
 * X-Service-Key 헤더로 인증합니다.
 */
public final class ServiceKeyAuthenticator {

    private static final String HEADER = "X-Service-Key";

    /** 설정되지 않았다면 null 또는 빈 문자열이며, 이 경우 서버 간 쓰기를 모두 거부합니다. */
    private final byte[] expectedKey;

    public ServiceKeyAuthenticator(String serviceApiKey) {
        this.expectedKey = serviceApiKey == null || serviceApiKey.isBlank()
                ? null
                : serviceApiKey.getBytes(StandardCharsets.UTF_8);
    }

    /** 서비스 키가 맞으면 true, 헤더가 없거나 다르면 false입니다. */
    public boolean matches(HttpExchange exchange) {
        String provided = exchange.getRequestHeaders().getFirst(HEADER);
        return expectedKey != null
                && provided != null
                && MessageDigest.isEqual(
                        expectedKey,
                        provided.getBytes(StandardCharsets.UTF_8)
                );
    }

    /** 쓰기 API용입니다. 키가 서버에 설정되지 않았거나 틀리면 거부합니다. */
    public void require(HttpExchange exchange) {
        if (expectedKey == null) {
            throw new ServiceUnavailableException(
                    "SERVICE_API_KEY 환경 변수가 설정되지 않아 쓰기 API를 사용할 수 없습니다.",
                    null
            );
        }
        if (!matches(exchange)) {
            throw new UnauthorizedException("유효한 X-Service-Key 헤더가 필요합니다.");
        }
    }
}
