package workplace.service;

import org.mindrot.jbcrypt.BCrypt;
import workplace.domain.User;
import workplace.domain.LoginRequest;
import workplace.domain.SignupRequest;
import workplace.exception.ConflictException;
import workplace.exception.UnauthorizedException;
import workplace.exception.ValidationException;
import workplace.repository.UserRepository;

/** 회원가입과 로그인 업무 규칙을 담당합니다. */
public final class AuthService {

    private static final int BCRYPT_COST = 12;

    private final UserRepository userRepository;

    public AuthService(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    /** 평문 비밀번호를 저장하지 않고 BCrypt 해시만 저장합니다. */
    public User signUp(SignupRequest request) {
        if (request == null) {
            throw new ValidationException("회원가입 요청 본문이 필요합니다.");
        }

        SignupRequest normalized = new SignupRequest(
                normalizeBusinessRegistrationNumber(request.businessRegistrationNumber()),
                validatePassword(request.password()),
                required(request.corporateName(), "법인명", 200),
                required(request.headOfficeAddress(), "본점 소재지", 500),
                required(request.businessType(), "업태", 100),
                required(request.businessItem(), "업종", 200),
                validateUnitTaxpayerApplicable(request.unitTaxpayerApplicable())
        );

        if (userRepository.findByBusinessRegistrationNumber(
                normalized.businessRegistrationNumber()
        ).isPresent()) {
            throw new ConflictException("이미 가입된 사업자등록번호입니다.");
        }

        String passwordHash = BCrypt.hashpw(
                normalized.password(),
                BCrypt.gensalt(BCRYPT_COST)
        );
        return userRepository.save(normalized, passwordHash);
    }

    /** 사용자 존재 여부와 비밀번호 오류를 같은 응답으로 처리합니다. */
    public User login(LoginRequest request) {
        if (request == null) {
            throw new ValidationException("로그인 요청 본문이 필요합니다.");
        }

        String businessRegistrationNumber = normalizeBusinessRegistrationNumber(
                request.businessRegistrationNumber()
        );
        String password = request.password() == null ? "" : request.password();

        User user = userRepository.findByBusinessRegistrationNumber(
                        businessRegistrationNumber
                )
                .orElseThrow(() -> new UnauthorizedException(
                        "사업자등록번호 또는 비밀번호가 올바르지 않습니다."
                ));

        if (!BCrypt.checkpw(password, user.passwordHash())) {
            throw new UnauthorizedException(
                    "사업자등록번호 또는 비밀번호가 올바르지 않습니다."
            );
        }
        return user;
    }

    /**
     * JWT 검증을 마친 사용자의 최신 가입 정보를 조회합니다.
     *
     * <p>주소·업태·업종을 토큰에 중복 저장하지 않고 DB에서 조회하므로,
     * 기존에 발급한 토큰도 그대로 사용할 수 있고 회원정보가 변경되면
     * 다음 인증 확인 요청부터 최신 값이 반영됩니다.</p>
     */
    public User getAuthenticatedUser(String businessRegistrationNumber) {
        return userRepository.findByBusinessRegistrationNumber(
                        businessRegistrationNumber
                )
                .orElseThrow(() -> new UnauthorizedException(
                        "인증된 사용자 정보를 찾을 수 없습니다."
                ));
    }

    private String normalizeBusinessRegistrationNumber(String rawNumber) {
        String number = rawNumber == null
                ? ""
                : rawNumber.trim().replace("-", "").replace(" ", "");
        if (!number.matches("^[0-9]{10}$")) {
            throw new ValidationException(
                    "사업자등록번호는 하이픈을 제외한 10자리 숫자여야 합니다."
            );
        }
        return number;
    }

    private String validatePassword(String rawPassword) {
        String password = rawPassword == null ? "" : rawPassword;
        if (password.isBlank() || password.length() < 8 || password.length() > 100) {
            throw new ValidationException("비밀번호는 8자 이상 100자 이하여야 합니다.");
        }
        return password;
    }

    private String required(String rawValue, String fieldName, int maxLength) {
        String value = rawValue == null ? "" : rawValue.trim();
        if (value.isEmpty() || value.length() > maxLength) {
            throw new ValidationException(
                    fieldName + "은(는) 1자 이상 " + maxLength + "자 이하여야 합니다."
            );
        }
        return value;
    }

    private String validateUnitTaxpayerApplicable(String rawValue) {
        String value = rawValue == null ? "" : rawValue.trim();
        if (!value.equals("여") && !value.equals("부")) {
            throw new ValidationException(
                    "사업자 단위 과세 적용사업자 여부는 '여' 또는 '부'여야 합니다."
            );
        }
        return value;
    }
}
