"""공개 업무 연락처는 보존하고, 이름과 개인 식별번호는 마스킹한다."""
import re

PHONE = re.compile(r"(?<!\d)(?:0\d{1,2}|1[568]\d{2})[- .)]?\s*\d{3,4}[- .]?\d{4}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
NAME = re.compile(r"((?:담당자|담당직원|성\s*명|대표자|담당관)\s*[:：]?\s*)([가-힣]{2,4})(?=\s|[,(/]|$)")


def mask_personal(text, names=()):
    text = re.sub(r"(?<!\d)\d{6}\s*[-–]\s*[1-8]\d{6}(?!\d)", "[주민번호 비공개]", text)
    text = re.sub(r"(계좌(?:번호)?\s*[:：]\s*)[\d -]{8,}", r"\1[계좌번호 비공개]", text)
    # 연락처를 먼저 보호한다. 이름이 이메일 로컬파트에 포함돼도 보존한다.
    protected = []
    def keep(match):
        protected.append(match.group())
        return f"\ue000{len(protected)-1}\ue001"
    text = EMAIL.sub(keep, text)
    text = PHONE.sub(keep, text)
    for name in sorted(set(names), key=len, reverse=True):
        if name and len(name.strip()) >= 2:
            text = re.sub(r"[ \t]*".join(re.escape(char) for char in name.strip()), "[이름 비공개]", text)
    text = NAME.sub(lambda m: m[1] + "[이름 비공개]" if m[2] not in
                    {"전화", "연락처", "이메일", "문의", "성명", "소속", "직위", "에게", "에게서", "에게는", "통해", "확인", "연락"} else m[0], text)
    text = re.sub(r"(?<![가-힣])([가-힣]{2,4})(팀장|주무관|차장|주임|대리)(?=\s|[,(☎]|$)",
                  r"[이름 비공개]\2", text)
    return re.sub(r"\ue000(\d+)\ue001", lambda m: protected[int(m[1])], text)


def extract_contacts(text, metadata=None):
    metadata = metadata or {}
    result = []
    for kind, regex, key in (("phone", PHONE, "ntceInsttOfclTelNo"),
                              ("email", EMAIL, "ntceInsttOfclEmailAdrs")):
        values = list(dict.fromkeys(([str(metadata[key])] if metadata.get(key) else []) + regex.findall(text)))
        result.extend({"type": kind, "value": value} for value in values)
    extra_email = metadata.get("dminsttOfclEmailAdrs")
    if extra_email and {"type": "email", "value": extra_email} not in result:
        result.append({"type": "email", "value": extra_email})
    return result


def official_names(item):
    return [item[k] for k in ("ntceInsttOfclNm", "exctvNm", "dminsttOfclNm") if item.get(k)]
