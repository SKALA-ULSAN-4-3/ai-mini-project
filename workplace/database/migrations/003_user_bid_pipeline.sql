-- 선택·승인 저장: 사업자등록번호 외래키, 공고·차수별 유일성 보장.
CREATE TABLE IF NOT EXISTS user_bid_pipeline (
    business_registration_number CHAR(10) NOT NULL,
    bid_no VARCHAR(100) NOT NULL,
    revision VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'selected',
    selected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (business_registration_number, bid_no, revision),
    CONSTRAINT fk_user_bid_pipeline_user FOREIGN KEY (business_registration_number)
        REFERENCES users (business_registration_number) ON DELETE CASCADE,
    CONSTRAINT chk_user_bid_pipeline_status CHECK (
        (status = 'selected' AND approved_at IS NULL)
        OR (status = 'approved' AND approved_at IS NOT NULL)
    ),
    CONSTRAINT chk_user_bid_pipeline_bid_no CHECK (bid_no ~ '^[A-Za-z0-9_-]{1,100}$'),
    CONSTRAINT chk_user_bid_pipeline_revision CHECK (revision ~ '^[A-Za-z0-9_-]{1,20}$')
);
-- 선택·승인 저장: 사업자등록번호 외래키, 공고·차수별 유일성 보장.
