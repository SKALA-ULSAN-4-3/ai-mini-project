package workplace.service;

import org.junit.jupiter.api.Test;
import workplace.domain.CompanyProfile;
import workplace.domain.CompanyProfileRequest;
import workplace.exception.ValidationException;
import workplace.repository.CompanyProfileRepository;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class CompanyProfileServiceTest {

    @Test
    void normalizesBlankAndDuplicateListValues() {
        RecordingRepository repository = new RecordingRepository();
        CompanyProfileService service = new CompanyProfileService(repository);
        CompanyProfileRequest request = request(100L, 500L);

        service.save("1234567890", request);

        assertEquals(List.of("소프트웨어사업자"), repository.saved.licenses());
    }

    @Test
    void rejectsInvalidBudgetRange() {
        CompanyProfileService service = new CompanyProfileService(
                new RecordingRepository()
        );

        assertThrows(
                ValidationException.class,
                () -> service.save("1234567890", request(600L, 500L))
        );
    }

    private CompanyProfileRequest request(Long minimum, Long maximum) {
        return new CompanyProfileRequest(
                "소프트웨어 개발",
                List.of(" 소프트웨어사업자 ", "", "소프트웨어사업자"),
                "서울특별시",
                "중소기업",
                List.of("벤처기업"),
                "A",
                List.of(),
                List.of("사업자등록증"),
                minimum,
                maximum,
                List.of("AI")
        );
    }

    private static final class RecordingRepository implements CompanyProfileRepository {

        private CompanyProfileRequest saved;

        @Override
        public Optional<CompanyProfile> findByBusinessRegistrationNumber(
                String businessRegistrationNumber
        ) {
            return Optional.empty();
        }

        @Override
        public CompanyProfile save(
                String businessRegistrationNumber,
                CompanyProfileRequest request
        ) {
            this.saved = request;
            return null;
        }
    }
}
