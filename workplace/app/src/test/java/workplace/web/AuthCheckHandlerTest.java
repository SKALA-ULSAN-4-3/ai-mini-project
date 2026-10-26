package workplace.web;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import workplace.domain.SignupRequest;
import workplace.domain.User;
import workplace.repository.UserRepository;
import workplace.security.JwtProvider;
import workplace.service.AuthService;
import workplace.web.handler.AuthCheckHandler;

import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;

/** 실제 HTTP 응답에 프론트가 사용하는 가입 정보 필드가 포함되는지 검증합니다. */
class AuthCheckHandlerTest {

    private final ObjectMapper mapper = new JsonCodec().objectMapper();
    private final HttpClient client = HttpClient.newHttpClient();
    private HttpServer server;
    private String endpoint;
    private String accessToken;

    @BeforeEach
    void start() throws Exception {
        User user = new User(
                "1234567890",
                "hash",
                "테스트 주식회사",
                "울산광역시 남구",
                "정보통신업",
                "소프트웨어 개발 및 공급업",
                "부"
        );
        UserRepository repository = new SingleUserRepository(user);
        AuthService authService = new AuthService(repository);
        JwtProvider jwtProvider = new JwtProvider(
                "test-secret-that-is-long-enough-for-hmac-sha256",
                "test",
                3600
        );
        accessToken = jwtProvider.createAccessToken(user);

        HttpResponses responses = new HttpResponses(mapper);
        AuthCheckHandler handler = new AuthCheckHandler(
                new CurrentUserResolver(jwtProvider),
                authService,
                responses
        );

        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext(
                "/api/auth/check",
                new ErrorHandlingHandler(handler, responses)
        );
        server.start();
        endpoint = "http://127.0.0.1:"
                + server.getAddress().getPort()
                + "/api/auth/check";
    }

    @AfterEach
    void stop() {
        server.stop(0);
    }

    @Test
    void returnsSignupFieldsWithSnakeCaseNames() throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create(endpoint))
                .header("Authorization", "Bearer " + accessToken)
                .GET()
                .build();

        HttpResponse<String> response = client.send(
                request,
                HttpResponse.BodyHandlers.ofString()
        );
        JsonNode body = mapper.readTree(response.body());

        assertEquals(200, response.statusCode());
        assertEquals("울산광역시 남구", body.get("head_office_address").asText());
        assertEquals("정보통신업", body.get("business_type").asText());
        assertEquals("소프트웨어 개발 및 공급업", body.get("business_item").asText());
    }

    /** DB 없이 인증 확인 응답을 검증하기 위한 단일 사용자 저장소입니다. */
    private record SingleUserRepository(User user) implements UserRepository {

        @Override
        public Optional<User> findByBusinessRegistrationNumber(
                String businessRegistrationNumber
        ) {
            if (user.businessRegistrationNumber().equals(businessRegistrationNumber)) {
                return Optional.of(user);
            }
            return Optional.empty();
        }

        @Override
        public User save(SignupRequest request, String passwordHash) {
            throw new UnsupportedOperationException("이 테스트에서는 저장하지 않습니다.");
        }
    }
}
