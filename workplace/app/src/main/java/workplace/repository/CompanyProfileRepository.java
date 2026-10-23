package workplace.repository;

import workplace.domain.CompanyProfile;
import workplace.domain.CompanyProfileRequest;

import java.util.Optional;

/** 회사 프로필 영속성 기능을 정의합니다. */
public interface CompanyProfileRepository {

    Optional<CompanyProfile> findByBusinessRegistrationNumber(
            String businessRegistrationNumber
    );

    CompanyProfile save(
            String businessRegistrationNumber,
            CompanyProfileRequest request
    );
}
