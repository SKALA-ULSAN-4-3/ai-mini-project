package workplace.domain;

import com.fasterxml.jackson.databind.JsonNode;

import java.time.LocalDate;
import java.util.List;

/** 회사별 공고 검색 캐시를 조회하거나 저장할 때 사용하는 요청입니다. */
public record SearchCacheRequest(
        LocalDate from,
        LocalDate to,
        List<String> queries,
        Integer limit,
        JsonNode result
) {
}
