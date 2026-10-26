package workplace.domain;

import java.time.Instant;
import java.util.List;
import java.util.Map;

/** DB에 저장된 회사 프로필 응답입니다. */
public record CompanyProfile(
        Long id,
        String businessRegistrationNumber,
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
        List<String> keywords,
        Instant createdAt,
        Instant updatedAt
) {
}
