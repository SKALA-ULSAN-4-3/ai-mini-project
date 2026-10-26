package workplace.service;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/**
 * 회사 프로필의 지역을 시·도 17개의 정식 명칭으로 맞춥니다.
 *
 * <p>공고 로직(bid_logic/common.py)이 인정하는 표기와 같은 목록입니다. 약칭과 옛 명칭도
 * 받아서 정식 명칭으로 저장합니다. "광주시"처럼 다른 지역과 겹치는 표기는 넣지 않습니다.
 */
final class Regions {

    private static final Map<String, String[]> NAMES = new LinkedHashMap<>();
    private static final Map<String, String> CANONICAL = new LinkedHashMap<>();

    static {
        NAMES.put("서울특별시", new String[]{"서울"});
        NAMES.put("부산광역시", new String[]{"부산"});
        NAMES.put("대구광역시", new String[]{"대구"});
        NAMES.put("인천광역시", new String[]{"인천"});
        NAMES.put("광주광역시", new String[]{"광주"});
        NAMES.put("대전광역시", new String[]{"대전"});
        NAMES.put("울산광역시", new String[]{"울산"});
        NAMES.put("세종특별자치시", new String[]{"세종", "세종시"});
        NAMES.put("경기도", new String[]{"경기"});
        NAMES.put("강원특별자치도", new String[]{"강원", "강원도"});
        NAMES.put("충청북도", new String[]{"충북"});
        NAMES.put("충청남도", new String[]{"충남"});
        NAMES.put("전북특별자치도", new String[]{"전북", "전라북도"});
        NAMES.put("전라남도", new String[]{"전남"});
        NAMES.put("경상북도", new String[]{"경북"});
        NAMES.put("경상남도", new String[]{"경남"});
        NAMES.put("제주특별자치도", new String[]{"제주", "제주도"});

        NAMES.forEach((official, aliases) -> {
            CANONICAL.put(official, official);
            for (String alias : aliases) {
                CANONICAL.put(alias, official);
            }
        });
    }

    private Regions() {
    }

    /** 시·도 정식 명칭 17개입니다. */
    static Set<String> officialNames() {
        return NAMES.keySet();
    }

    /**
     * 정식 명칭, 약칭, 옛 명칭을 정식 명칭으로 바꿉니다. "울산광역시 남구"처럼 시·도 뒤에
     * 시·군·구가 붙은 입력은 첫 단어로 판단합니다. 목록에 없으면 null입니다.
     */
    static String canonical(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        String exact = CANONICAL.get(trimmed);
        if (exact != null) {
            return exact;
        }
        // 공백으로 나뉜 첫 단어만 봅니다. "광주시"처럼 붙여 쓴 모호한 표기는 걸러집니다.
        int space = trimmed.indexOf(' ');
        return space < 0 ? null : CANONICAL.get(trimmed.substring(0, space));
    }
}
