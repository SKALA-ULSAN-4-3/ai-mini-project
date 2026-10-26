package workplace.config;

import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;

/** 환경 변수에서 읽은 서버 설정을 한곳에 보관합니다. */
public record AppConfig(
        int serverPort,
        String databaseUrl,
        String databaseUser,
        String databasePassword,
        String jwtSecret,
        String jwtIssuer,
        long jwtExpirationSeconds,
        Set<String> allowedOrigins,
        String serviceApiKey,
        String supabaseUrl,
        String supabaseServiceKey,
        String supabaseBucket
) {

    /** 환경 변수를 읽고 필수 설정 누락 여부를 즉시 검증합니다. */
    public static AppConfig fromEnvironment() {
        return new AppConfig(
                integerValue("SERVER_PORT", 8080),
                value("DB_URL", "jdbc:postgresql://localhost:54321/workplace_db"),
                value("DB_USER", "workplace_app"),
                required("DB_PASSWORD"),
                required("JWT_SECRET"),
                value("JWT_ISSUER", "simple-auth-server"),
                longValue("JWT_EXPIRATION_SECONDS", 3600L),
                origins(value(
                        "CORS_ORIGINS",
                        "http://localhost:5174,http://127.0.0.1:5174,"
                                + "http://localhost:8008,http://127.0.0.1:8008"
                )),
                value("SERVICE_API_KEY", ""),
                value("SUPABASE_URL", ""),
                value("SUPABASE_SERVICE_KEY", ""),
                value("SUPABASE_BUCKET", "documents")
        );
    }

    /** PDF 저장소(Supabase)가 설정되었는지 알려 줍니다. 미설정이면 문서 API만 비활성화됩니다. */
    public boolean supabaseConfigured() {
        return !supabaseUrl.isEmpty() && !supabaseServiceKey.isEmpty();
    }

    private static String required(String name) {
        String result = System.getenv(name);
        if (result == null || result.isBlank()) {
            throw new IllegalStateException(name + " 환경 변수가 필요합니다.");
        }
        return result.trim();
    }

    private static String value(String name, String defaultValue) {
        String result = System.getenv(name);
        return result == null || result.isBlank() ? defaultValue : result.trim();
    }

    private static int integerValue(String name, int defaultValue) {
        return Integer.parseInt(value(name, String.valueOf(defaultValue)));
    }

    private static long longValue(String name, long defaultValue) {
        return Long.parseLong(value(name, String.valueOf(defaultValue)));
    }

    private static Set<String> origins(String rawOrigins) {
        return Arrays.stream(rawOrigins.split(","))
                .map(String::trim)
                .filter(origin -> !origin.isEmpty())
                .collect(Collectors.toUnmodifiableSet());
    }
}
