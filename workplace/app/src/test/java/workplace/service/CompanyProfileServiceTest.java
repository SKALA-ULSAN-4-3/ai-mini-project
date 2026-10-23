package workplace.service;

import org.junit.jupiter.api.Test;
import workplace.domain.CompanyProfile;
import workplace.domain.CompanyProfileRequest;
import workplace.exception.ValidationException;
import workplace.repository.CompanyProfileRepository;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
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

    @Test
    void storesRegionAsOfficialProvinceName() {
        RecordingRepository repository = new RecordingRepository();
        CompanyProfileService service = new CompanyProfileService(repository);

        service.save("1234567890", requestIn(" 울산 "));
        assertEquals("울산광역시", repository.saved.region());

        service.save("1234567890", requestIn("전라북도"));
        assertEquals("전북특별자치도", repository.saved.region());

        service.save("1234567890", requestIn("경기도"));
        assertEquals("경기도", repository.saved.region());
    }

    @Test
    void takesProvinceFromAddressStyleInput() {
        RecordingRepository repository = new RecordingRepository();
        CompanyProfileService service = new CompanyProfileService(repository);

        service.save("1234567890", requestIn("울산광역시 남구"));
        assertEquals("울산광역시", repository.saved.region());

        service.save("1234567890", requestIn("경기도 광주시"));
        assertEquals("경기도", repository.saved.region());

        service.save("1234567890", requestIn("서울 강남구"));
        assertEquals("서울특별시", repository.saved.region());
    }

    @Test
    void keepsNullAsUnknownAndEmptyListAsNone() {
        RecordingRepository repository = new RecordingRepository();
        CompanyProfileService service = new CompanyProfileService(repository);
        CompanyProfileRequest base = request(100L, 500L);

        service.save("1234567890", new CompanyProfileRequest(
                base.industry(), null, base.region(), base.companySize(),
                null, base.creditRating(), null, null,
                base.budgetMin(), base.budgetMax(), null
        ));
        assertNull(repository.saved.licenses());
        assertNull(repository.saved.certs());
        assertNull(repository.saved.trackRecords());
        assertNull(repository.saved.ownedDocs());
        assertNull(repository.saved.keywords());

        service.save("1234567890", new CompanyProfileRequest(
                base.industry(), List.of(), base.region(), base.companySize(),
                List.of(), base.creditRating(), List.of(), List.of(),
                base.budgetMin(), base.budgetMax(), List.of()
        ));
        assertEquals(List.of(), repository.saved.licenses());
        assertEquals(List.of(), repository.saved.certs());
        assertEquals(List.of(), repository.saved.trackRecords());
        assertEquals(List.of(), repository.saved.ownedDocs());
        assertEquals(List.of(), repository.saved.keywords());
    }

    @Test
    void rejectsRegionOutsideProvinceList() {
        CompanyProfileService service = new CompanyProfileService(
                new RecordingRepository()
        );

        for (String region : new String[]{"울산광역시남구", "광주시", "남구", "", "  ", null}) {
            assertThrows(
                    ValidationException.class,
                    () -> service.save("1234567890", requestIn(region)),
                    String.valueOf(region)
            );
        }
    }

    private CompanyProfileRequest requestIn(String region) {
        CompanyProfileRequest base = request(100L, 500L);
        return new CompanyProfileRequest(
                base.industry(), base.licenses(), region, base.companySize(),
                base.certs(), base.creditRating(), base.trackRecords(),
                base.ownedDocs(), base.budgetMin(), base.budgetMax(), base.keywords()
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
