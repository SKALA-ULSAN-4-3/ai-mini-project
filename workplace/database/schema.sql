-- 로컬 실행과 Kubernetes 최초 초기화가 같은 데이터베이스를 사용하도록
-- 애플리케이션 기본 DB를 명시적으로 생성하고 선택합니다.
CREATE DATABASE IF NOT EXISTS sql_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE sql_db;

-- Java 인증 서버가 관리하는 사업자 회원 테이블입니다.
-- 사업자등록번호는 하이픈을 제거한 10자리 숫자로 저장합니다.
CREATE TABLE IF NOT EXISTS users (
    business_registration_number CHAR(10) NOT NULL,
    password VARCHAR(255) NOT NULL,
    corporate_name VARCHAR(200) NOT NULL,
    head_office_address VARCHAR(500) NOT NULL,
    business_type VARCHAR(100) NOT NULL,
    business_item VARCHAR(200) NOT NULL,
    unit_taxpayer_applicable CHAR(1) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (business_registration_number),

    CONSTRAINT chk_users_business_registration_number
        CHECK (business_registration_number REGEXP '^[0-9]{10}$'),

    CONSTRAINT chk_users_unit_taxpayer_applicable
        CHECK (unit_taxpayer_applicable IN ('여', '부'))
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

-- JWT sub(사업자등록번호)를 키로 사용자 한 명당 회사 프로필 하나를 저장합니다.
CREATE TABLE IF NOT EXISTS company_profiles (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    business_registration_number CHAR(10) NOT NULL,

    industry VARCHAR(200) NOT NULL,
    licenses JSON NOT NULL,
    region VARCHAR(100) NOT NULL,
    company_size VARCHAR(50) NOT NULL,
    certs JSON NOT NULL,
    credit_rating VARCHAR(50) NULL,
    track_records JSON NOT NULL,
    owned_docs JSON NOT NULL,
    budget_min BIGINT UNSIGNED NULL,
    budget_max BIGINT UNSIGNED NULL,
    keywords JSON NOT NULL,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_company_profiles_business_number (business_registration_number),

    CONSTRAINT fk_company_profiles_user
        FOREIGN KEY (business_registration_number)
        REFERENCES users (business_registration_number)
        ON DELETE CASCADE,

    CONSTRAINT chk_company_profiles_budget
        CHECK (
            budget_min IS NULL
            OR budget_max IS NULL
            OR budget_min <= budget_max
        )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;
