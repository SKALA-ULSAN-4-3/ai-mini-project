package workplace.service;

import org.junit.jupiter.api.Test;
import workplace.domain.LoginRequest;
import workplace.domain.SignupRequest;
import workplace.domain.User;
import workplace.exception.UnauthorizedException;
import workplace.exception.ValidationException;
import workplace.repository.UserRepository;

import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class AuthServiceTest {

    @Test
    void signsUpWithNormalizedBusinessRegistrationNumberAndHashedPassword() {
        RecordingUserRepository repository = new RecordingUserRepository();
        AuthService service = new AuthService(repository);

        User user = service.signUp(signupRequest("123-45-67890", "여"));

        assertEquals("1234567890", user.businessRegistrationNumber());
        assertNotEquals("password123!", user.passwordHash());
        assertEquals("여", user.unitTaxpayerApplicable());
    }

    @Test
    void logsInWithFormattedBusinessRegistrationNumber() {
        RecordingUserRepository repository = new RecordingUserRepository();
        AuthService service = new AuthService(repository);
        service.signUp(signupRequest("1234567890", "부"));

        User user = service.login(new LoginRequest("123-45-67890", "password123!"));

        assertEquals("테스트 주식회사", user.corporateName());
    }

    @Test
    void rejectsInvalidUnitTaxpayerValue() {
        AuthService service = new AuthService(new RecordingUserRepository());

        assertThrows(
                ValidationException.class,
                () -> service.signUp(signupRequest("1234567890", "Y"))
        );
    }

    @Test
    void doesNotRevealWhetherBusinessNumberExistsDuringLogin() {
        AuthService service = new AuthService(new RecordingUserRepository());

        assertThrows(
                UnauthorizedException.class,
                () -> service.login(new LoginRequest("1234567890", "password123!"))
        );
    }

    private SignupRequest signupRequest(String businessNumber, String unitTaxpayer) {
        return new SignupRequest(
                businessNumber,
                "password123!",
                " 테스트 주식회사 ",
                " 울산광역시 남구 ",
                " 정보통신업 ",
                " 소프트웨어 개발 및 공급업 ",
                unitTaxpayer
        );
    }

    /** 외부 DB 없이 서비스의 검증·해시 규칙만 확인하는 메모리 저장소입니다. */
    private static final class RecordingUserRepository implements UserRepository {

        private User saved;

        @Override
        public Optional<User> findByBusinessRegistrationNumber(
                String businessRegistrationNumber
        ) {
            if (saved == null
                    || !saved.businessRegistrationNumber().equals(
                    businessRegistrationNumber
            )) {
                return Optional.empty();
            }
            return Optional.of(saved);
        }

        @Override
        public User save(SignupRequest request, String passwordHash) {
            saved = new User(
                    request.businessRegistrationNumber(),
                    passwordHash,
                    request.corporateName(),
                    request.headOfficeAddress(),
                    request.businessType(),
                    request.businessItem(),
                    request.unitTaxpayerApplicable()
            );
            return saved;
        }
    }
}
