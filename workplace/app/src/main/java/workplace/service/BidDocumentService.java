package workplace.service;

import workplace.domain.BidDocument;
import workplace.domain.BidDocumentView;
import workplace.exception.ConflictException;
import workplace.exception.ServiceUnavailableException;
import workplace.exception.ValidationException;
import workplace.repository.BidDocumentRepository;
import workplace.storage.DocumentStorage;

import java.util.List;
import java.util.UUID;
import java.util.Locale;
import java.util.HexFormat;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.logging.Level;
import java.util.logging.Logger;

/** 공고 원본·변환 파일을 Storage에 올리고 위치를 DB에 기록하는 유스케이스를 담당합니다. */
public final class BidDocumentService {

    public static final long MAX_PDF_BYTES = 50L * 1024 * 1024;
    public static final long DOWNLOAD_URL_TTL_SECONDS = 3600L;

    private static final Logger LOGGER = Logger.getLogger(BidDocumentService.class.getName());
    private static final String PDF = "application/pdf";
    private static final byte[] PDF_MAGIC = {'%', 'P', 'D', 'F', '-'};

    private final BidDocumentRepository repository;
    /** Supabase 설정이 없으면 null이며, 이 경우 문서 기능은 503을 돌려줍니다. */
    private final DocumentStorage storage;

    public BidDocumentService(BidDocumentRepository repository, DocumentStorage storage) {
        this.repository = repository;
        this.storage = storage;
    }

    /** Storage 업로드가 성공한 뒤에만 DB에 기록하고, DB 실패 시 올린 파일을 지웁니다. */
    public BidDocumentView upload(
            String bidNo,
            String revision,
            String fileName,
            String sourceUrl,
            byte[] content
    ) {
        DocumentStorage activeStorage = requireStorage();
        String normalizedBidNo = BidIds.bidNo(bidNo);
        String normalizedRevision = BidIds.revision(revision);
        String normalizedFileName = fileName(fileName);
        String normalizedSourceUrl = sourceUrl(sourceUrl);
        validateContent(normalizedFileName, content);

        if (repository.exists(normalizedBidNo, normalizedRevision, normalizedFileName)) {
            throw new ConflictException("이미 등록된 파일명입니다.");
        }

        // 원본 파일명은 한글·공백이 있을 수 있어 Storage 키에는 쓰지 않고 DB에만 남깁니다.
        String storageKey = "bids/" + normalizedBidNo + "/" + normalizedRevision
                + "/" + UUID.randomUUID() + extension(normalizedFileName);
        activeStorage.upload(storageKey, content, contentType(normalizedFileName));

        try {
            BidDocument saved = repository.save(
                    normalizedBidNo,
                    normalizedRevision,
                    normalizedFileName,
                    storageKey,
                    content.length,
                    normalizedSourceUrl
            );
            return BidDocumentView.of(saved, null, null);
        } catch (RuntimeException exception) {
            try {
                activeStorage.delete(storageKey);
            } catch (RuntimeException cleanupFailure) {
                LOGGER.log(Level.WARNING,
                        "DB 저장 실패 후 Storage 정리에 실패했습니다. key=" + storageKey,
                        cleanupFailure);
            }
            throw exception;
        }
    }

    /** 차수를 생략하면 모든 차수를 돌려주며, 각 파일에 임시 다운로드 주소를 붙입니다. */
    public List<BidDocumentView> list(String bidNo, String revision) {
        return list(bidNo, revision, false, true, null);
    }

    public List<BidDocumentView> list(String bidNo, String revision,
                                      boolean includeInternal, boolean signedUrls, String fileName) {
        DocumentStorage activeStorage = requireStorage();
        String normalizedRevision =
                revision == null || revision.isBlank() ? null : BidIds.revision(revision);

        return repository.findByBid(BidIds.bidNo(bidNo), normalizedRevision).stream()
                .filter(document -> includeInternal || !document.fileName().startsWith("dp1_state_"))
                .filter(document -> fileName == null || fileName.equals(document.fileName()))
                .map(document -> BidDocumentView.of(
                        document,
                        signedUrls ? activeStorage.createSignedUrl(
                                document.storageKey(), DOWNLOAD_URL_TTL_SECONDS) : null,
                        signedUrls ? DOWNLOAD_URL_TTL_SECONDS : null
                ))
                .toList();
    }

    /** 요약 응답에 덧붙일 용도입니다. 저장소가 설정되지 않았으면 빈 목록을 돌려줍니다. */
    public List<BidDocumentView> linksOrEmpty(String bidNo, String revision) {
        return storage == null ? List.of() : list(bidNo, revision);
    }

    private DocumentStorage requireStorage() {
        if (storage == null) {
            throw new ServiceUnavailableException(
                    "문서 저장소(Supabase) 설정이 필요합니다.",
                    null
            );
        }
        return storage;
    }

    private String fileName(String raw) {
        String value = raw == null ? "" : raw.trim();
        if (value.isEmpty() || value.length() > 500) {
            throw new ValidationException("file_name은 1자 이상 500자 이하여야 합니다.");
        }
        return value;
    }

    private String sourceUrl(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        return raw.trim();
    }

    private String extension(String name) {
        int dot = name.lastIndexOf('.');
        String suffix = dot < 0 ? "" : name.substring(dot).toLowerCase(Locale.ROOT);
        return suffix.matches("\\.[a-z0-9]{1,10}") ? suffix : ".bin";
    }

    private String contentType(String name) {
        return switch (extension(name)) {
            case ".pdf" -> PDF;
            case ".json" -> "application/json";
            case ".zip", ".hwpx" -> "application/zip";
            case ".txt", ".csv" -> "text/plain";
            case ".png" -> "image/png";
            case ".jpg", ".jpeg" -> "image/jpeg";
            default -> "application/octet-stream";
        };
    }

    private void validateContent(String name, byte[] content) {
        if (content == null || content.length == 0 || content.length > MAX_PDF_BYTES) {
            throw new ValidationException("첨부파일은 비어 있지 않은 최대 50MB 파일이어야 합니다.");
        }
        String suffix = extension(name);
        if (name.startsWith("dp1_")) {
            String[] parts = name.split("_", 5);
            try {
                String digest = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content));
                if (parts.length != 5 || !digest.equals(parts[3])) {
                    throw new ValidationException("첨부파일 내용 해시가 일치하지 않습니다.");
                }
            } catch (NoSuchAlgorithmException exception) {
                throw new IllegalStateException("SHA-256을 사용할 수 없습니다.", exception);
            }
        }
        if (".pdf".equals(suffix)) {
            if (content.length < PDF_MAGIC.length) throw new ValidationException("올바른 PDF 파일이 아닙니다.");
            for (int i = 0; i < PDF_MAGIC.length; i++) {
                if (content[i] != PDF_MAGIC[i]) throw new ValidationException("올바른 PDF 파일이 아닙니다.");
            }
        }
    }
}
