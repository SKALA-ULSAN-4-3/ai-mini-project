package workplace.storage;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import workplace.exception.ServiceUnavailableException;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;

/** Supabase Storage REST API로 비공개 버킷의 PDF를 저장·조회·삭제합니다. */
public final class SupabaseDocumentStorage implements DocumentStorage {

    private static final Duration TIMEOUT = Duration.ofSeconds(60);

    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .build();
    private final ObjectMapper objectMapper;
    private final String baseUrl;
    private final String serviceKey;
    private final String bucket;

    public SupabaseDocumentStorage(
            ObjectMapper objectMapper,
            String projectUrl,
            String serviceKey,
            String bucket
    ) {
        this.objectMapper = objectMapper;
        this.baseUrl = projectUrl.replaceAll("/+$", "") + "/storage/v1";
        this.serviceKey = serviceKey;
        this.bucket = bucket;
    }

    @Override
    public void upload(String storageKey, byte[] content, String contentType) {
        HttpRequest request = authorized("/object/" + bucket + "/" + storageKey)
                .header("Content-Type", contentType)
                .header("x-upsert", "false")
                .POST(HttpRequest.BodyPublishers.ofByteArray(content))
                .build();
        send(request, "PDF를 저장소에 업로드할 수 없습니다.");
    }

    @Override
    public String createSignedUrl(String storageKey, long expiresInSeconds) {
        try {
            byte[] body = objectMapper.writeValueAsBytes(Map.of("expiresIn", expiresInSeconds));
            HttpRequest request = authorized("/object/sign/" + bucket + "/" + storageKey)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofByteArray(body))
                    .build();

            HttpResponse<String> response = send(request, "PDF 다운로드 주소를 만들 수 없습니다.");
            JsonNode signed = objectMapper.readTree(response.body()).get("signedURL");
            if (signed == null || signed.asText().isBlank()) {
                throw new ServiceUnavailableException("PDF 다운로드 주소를 만들 수 없습니다.", null);
            }
            return baseUrl + signed.asText();
        } catch (IOException exception) {
            throw new ServiceUnavailableException("PDF 다운로드 주소를 만들 수 없습니다.", exception);
        }
    }

    @Override
    public void delete(String storageKey) {
        HttpRequest request = authorized("/object/" + bucket + "/" + storageKey)
                .DELETE()
                .build();
        send(request, "저장소의 PDF를 삭제할 수 없습니다.");
    }

    private HttpRequest.Builder authorized(String path) {
        return HttpRequest.newBuilder(URI.create(baseUrl + path))
                .timeout(TIMEOUT)
                .header("Authorization", "Bearer " + serviceKey)
                .header("apikey", serviceKey);
    }

    private HttpResponse<String> send(HttpRequest request, String failureMessage) {
        try {
            HttpResponse<String> response =
                    httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() / 100 != 2) {
                throw new ServiceUnavailableException(
                        failureMessage + " (storage status " + response.statusCode() + ")",
                        new IllegalStateException(response.body())
                );
            }
            return response;
        } catch (IOException exception) {
            throw new ServiceUnavailableException(failureMessage, exception);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new ServiceUnavailableException(failureMessage, exception);
        }
    }
}
