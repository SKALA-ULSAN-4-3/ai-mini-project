package workplace.domain;

import com.fasterxml.jackson.databind.JsonNode;

/** 공고번호별 제안요청서 처리 결과를 저장하는 요청입니다. */
public record RfpCacheRequest(
        String revision,
        JsonNode result
) {
}
