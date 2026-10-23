package workplace.domain;

import java.util.List;
import java.util.Map;

/** 회사 프로필 생성·수정 요청입니다. */
public record CompanyProfileRequest(
        String industry,
        List<String> licenses,
        String region,
        String companySize,
        List<String> certs,
        String creditRating,
        List<Map<String, Object>> trackRecords,
        List<String> ownedDocs,
        Long budgetMin,
        Long budgetMax,
        List<String> keywords
) {
}
