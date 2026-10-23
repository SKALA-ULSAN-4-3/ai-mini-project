package workplace.storage;

/** PDF 파일 본문을 보관하는 외부 저장소를 추상화합니다. */
public interface DocumentStorage {

    void upload(String storageKey, byte[] content, String contentType);

    /** 비공개 파일을 제한 시간 동안만 내려받을 수 있는 주소를 만듭니다. */
    String createSignedUrl(String storageKey, long expiresInSeconds);

    void delete(String storageKey);
}
