package workplace.domain;

/** 모든 항목이 필수인 사업자 회원가입 요청입니다. */
public record SignupRequest(
        String businessRegistrationNumber,
        String password,
        String corporateName,
        String headOfficeAddress,
        String businessType,
        String businessItem,
        String unitTaxpayerApplicable
) {
}
