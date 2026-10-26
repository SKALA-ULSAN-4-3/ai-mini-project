package workplace.domain;

import com.fasterxml.jackson.databind.JsonNode;

import java.time.Instant;

/** 캐시 적중 여부를 오류 없이 구분할 수 있는 공통 HTTP 응답입니다. */
public record CacheResponse(
        boolean cached,
        JsonNode result,
        Instant createdAt,
        Instant expiresAt
) {
    public static CacheResponse hit(CachedResult cachedResult) {
        return new CacheResponse(
                true,
                cachedResult.result(),
                cachedResult.createdAt(),
                cachedResult.expiresAt()
        );
    }

    public static CacheResponse miss() {
        return new CacheResponse(false, null, null, null);
    }
}
