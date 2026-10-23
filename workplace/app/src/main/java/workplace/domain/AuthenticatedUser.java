package workplace.domain;

/** 검증된 JWT에서 꺼낸 사업자 회원 식별 정보입니다. */
public record AuthenticatedUser(
        String businessRegistrationNumber,
        String corporateName
) {
}
