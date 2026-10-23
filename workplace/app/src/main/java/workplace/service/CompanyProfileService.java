package workplace.service;

import workplace.domain.CompanyProfile;
import workplace.domain.CompanyProfileRequest;
import workplace.exception.NotFoundException;
import workplace.exception.ValidationException;
import workplace.repository.CompanyProfileRepository;

import java.util.LinkedHashSet;
import java.util.List;

/** 프로필 검증과 조회·저장 유스케이스를 담당합니다. */
public final class CompanyProfileService {

    private final CompanyProfileRepository repository;

    public CompanyProfileService(CompanyProfileRepository repository) {
        this.repository = repository;
    }

    public CompanyProfile get(String businessRegistrationNumber) {
        return repository.findByBusinessRegistrationNumber(businessRegistrationNumber)
                .orElseThrow(() -> new NotFoundException("등록된 회사 프로필이 없습니다."));
    }

    public CompanyProfile save(
            String businessRegistrationNumber,
            CompanyProfileRequest request
    ) {
        CompanyProfileRequest normalized = normalize(request);
        validateBudget(normalized.budgetMin(), normalized.budgetMax());
        return repository.save(businessRegistrationNumber, normalized);
    }

    private CompanyProfileRequest normalize(CompanyProfileRequest request) {
        if (request == null) {
            throw new ValidationException("회사 프로필 요청 본문이 필요합니다.");
        }

        return new CompanyProfileRequest(
                required(request.industry(), "industry", 200),
                strings(request.licenses()),
                region(request.region()),
                required(request.companySize(), "company_size", 50),
                strings(request.certs()),
                optional(request.creditRating(), 50),
                request.trackRecords() == null ? null : List.copyOf(request.trackRecords()),
                strings(request.ownedDocs()),
                request.budgetMin(),
                request.budgetMax(),
                strings(request.keywords())
        );
    }

    private String required(String value, String field, int maxLength) {
        String normalized = value == null ? "" : value.trim();
        if (normalized.isEmpty() || normalized.length() > maxLength) {
            throw new ValidationException(
                    field + " 값은 1자 이상 " + maxLength + "자 이하여야 합니다."
            );
        }
        return normalized;
    }

    private String region(String value) {
        String canonical = Regions.canonical(value);
        if (canonical == null) {
            throw new ValidationException(
                    "region 값은 시·도 17개 중 하나여야 합니다. 예: 서울특별시, 울산광역시"
            );
        }
        return canonical;
    }

    private String optional(String value, int maxLength) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String normalized = value.trim();
        if (normalized.length() > maxLength) {
            throw new ValidationException("credit_rating 값이 너무 깁니다.");
        }
        return normalized;
    }

    /**
     * null(안 적음·모름)은 그대로 null로 두고, 빈 목록([])은 "없음 확인"으로 유지합니다.
     * 공고 로직이 이 둘을 다르게 해석하므로 서로 바꾸면 안 됩니다.
     */
    private List<String> strings(List<String> values) {
        if (values == null) {
            return null;
        }

        LinkedHashSet<String> normalized = new LinkedHashSet<>();
        for (String value : values) {
            if (value != null && !value.isBlank()) {
                normalized.add(value.trim());
            }
        }
        return List.copyOf(normalized);
    }

    private void validateBudget(Long minimum, Long maximum) {
        if (minimum != null && minimum < 0 || maximum != null && maximum < 0) {
            throw new ValidationException("희망 금액은 0 이상이어야 합니다.");
        }
        if (minimum != null && maximum != null && minimum > maximum) {
            throw new ValidationException("budget_min은 budget_max보다 클 수 없습니다.");
        }
    }
}
