package workplace.service;

import workplace.exception.ValidationException;

import java.util.regex.Pattern;

/** 공고번호·차수 형식을 검증합니다. Storage 경로에 그대로 쓰이므로 안전한 문자만 허용합니다. */
final class BidIds {

    static final String DEFAULT_REVISION = "000";

    private static final Pattern BID_NO = Pattern.compile("^[A-Za-z0-9_-]{1,100}$");
    private static final Pattern REVISION = Pattern.compile("^[A-Za-z0-9_-]{1,20}$");

    private BidIds() {
    }

    static String bidNo(String raw) {
        String value = raw == null ? "" : raw.trim();
        if (!BID_NO.matcher(value).matches()) {
            throw new ValidationException(
                    "bid_no는 영문·숫자·하이픈·밑줄 1~100자여야 합니다."
            );
        }
        return value;
    }

    static String revision(String raw) {
        if (raw == null || raw.isBlank()) {
            return DEFAULT_REVISION;
        }
        String value = raw.trim();
        if (!REVISION.matcher(value).matches()) {
            throw new ValidationException(
                    "revision은 영문·숫자·하이픈·밑줄 1~20자여야 합니다."
            );
        }
        return value;
    }
}
