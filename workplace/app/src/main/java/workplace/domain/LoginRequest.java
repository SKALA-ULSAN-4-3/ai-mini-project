package workplace.domain;

/** 사업자등록번호와 비밀번호로 로그인하는 요청입니다. */
public record LoginRequest(
        String businessRegistrationNumber,
        String password
) {
}
