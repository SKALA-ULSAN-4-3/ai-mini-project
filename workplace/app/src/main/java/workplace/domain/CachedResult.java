package workplace.domain;

import com.fasterxml.jackson.databind.JsonNode;

import java.time.Instant;

/** 아직 만료되지 않은 캐시 결과와 유효기간입니다. */
public record CachedResult(
        JsonNode result,
        Instant createdAt,
        Instant expiresAt
) {
}
