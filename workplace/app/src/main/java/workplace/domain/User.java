package workplace.domain;

/** 회원가입 테이블에 저장되는 사업자 회원 정보입니다. */
public record User(
        String businessRegistrationNumber,
        String passwordHash,
        String corporateName,
        String headOfficeAddress,
        String businessType,
        String businessItem,
        String unitTaxpayerApplicable
) {
}
