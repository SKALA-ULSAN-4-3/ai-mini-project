package workplace;

import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;
import workplace.config.AppConfig;
import workplace.repository.JdbcPipelineRepository;
import workplace.service.PipelineService;
import workplace.web.handler.PipelineHandler;
import workplace.repository.BidDocumentRepository;
import workplace.repository.BidSummaryRepository;
import workplace.repository.BidCacheRepository;
import workplace.repository.CompanyProfileRepository;
import workplace.repository.ConnectionFactory;
import workplace.repository.DriverManagerConnectionFactory;
import workplace.repository.JdbcBidDocumentRepository;
import workplace.repository.JdbcBidSummaryRepository;
import workplace.repository.JdbcBidCacheRepository;
import workplace.repository.JdbcCompanyProfileRepository;
import workplace.repository.JdbcUserRepository;
import workplace.repository.UserRepository;
import workplace.security.JwtProvider;
import workplace.service.AuthService;
import workplace.service.BidDocumentService;
import workplace.service.BidSummaryService;
import workplace.service.BidCacheService;
import workplace.service.CompanyProfileService;
import workplace.web.CorsHandler;
import workplace.web.CurrentUserResolver;
import workplace.web.ErrorHandlingHandler;
import workplace.web.HttpResponses;
import workplace.web.JsonCodec;
import workplace.web.RequestBodies;
import workplace.web.RequestLoggingHandler;
import workplace.web.ServiceKeyAuthenticator;
import workplace.storage.DocumentStorage;
import workplace.storage.SupabaseDocumentStorage;
import workplace.web.handler.AuthCheckHandler;
import workplace.web.handler.BidHandler;
import workplace.web.handler.BidCacheHandler;
import workplace.web.handler.HealthHandler;
import workplace.web.handler.LoginHandler;
import workplace.web.handler.LivenessHandler;
import workplace.web.handler.ProfileHandler;
import workplace.web.handler.RedirectHandler;
import workplace.web.handler.SignupHandler;
import workplace.web.handler.StaticResourceHandler;

import java.net.InetSocketAddress;
import java.util.concurrent.Executors;

/**
 * 백엔드의 객체 생성과 엔드포인트 등록만 담당하는 애플리케이션 진입점입니다.
 *
 * <p>HTTP, 서비스, Repository, 보안 구현을 여기에서 조립하되 각 계층의
 * 실제 로직은 해당 클래스에 위임합니다.</p>
 */
public final class WorkplaceApplication {

    private WorkplaceApplication() {
    }

    public static void main(String[] args) throws Exception {
        AppConfig config = AppConfig.fromEnvironment();
        Class.forName("org.postgresql.Driver");

        JsonCodec jsonCodec = new JsonCodec();
        HttpResponses responses = new HttpResponses(jsonCodec.objectMapper());
        RequestBodies requestBodies = new RequestBodies(jsonCodec.objectMapper());

        ConnectionFactory connectionFactory = new DriverManagerConnectionFactory(
                config.databaseUrl(),
                config.databaseUser(),
                config.databasePassword()
        );

        UserRepository userRepository = new JdbcUserRepository(connectionFactory);
        CompanyProfileRepository profileRepository = new JdbcCompanyProfileRepository(
                connectionFactory,
                jsonCodec.objectMapper()
        );

        BidSummaryRepository bidSummaryRepository = new JdbcBidSummaryRepository(
                connectionFactory,
                jsonCodec.objectMapper()
        );
        BidCacheRepository bidCacheRepository = new JdbcBidCacheRepository(
                connectionFactory,
                jsonCodec.objectMapper()
        );
        BidDocumentRepository bidDocumentRepository =
                new JdbcBidDocumentRepository(connectionFactory);
        DocumentStorage documentStorage = config.supabaseConfigured()
                ? new SupabaseDocumentStorage(
                        jsonCodec.objectMapper(),
                        config.supabaseUrl(),
                        config.supabaseServiceKey(),
                        config.supabaseBucket()
                )
                : null;

        AuthService authService = new AuthService(userRepository);
        CompanyProfileService profileService = new CompanyProfileService(profileRepository);
        BidSummaryService bidSummaryService = new BidSummaryService(bidSummaryRepository);
        BidCacheService bidCacheService = new BidCacheService(
                bidCacheRepository,
                profileService
        );
        BidDocumentService bidDocumentService =
                new BidDocumentService(bidDocumentRepository, documentStorage);
        ServiceKeyAuthenticator serviceKeys =
                new ServiceKeyAuthenticator(config.serviceApiKey());
        JwtProvider jwtProvider = new JwtProvider(
                config.jwtSecret(),
                config.jwtIssuer(),
                config.jwtExpirationSeconds()
        );
        CurrentUserResolver currentUserResolver = new CurrentUserResolver(jwtProvider);

        PipelineService pipelineService = new PipelineService(
                new JdbcPipelineRepository(connectionFactory));

        HttpServer server = HttpServer.create(
                new InetSocketAddress(config.serverPort()),
                0
        );
        server.setExecutor(Executors.newFixedThreadPool(10));

        register(
                server,
                "/api/signup",
                new SignupHandler(authService, requestBodies, responses),
                responses,
                config
        );
        register(
                server,
                "/api/login",
                new LoginHandler(
                        authService,
                        jwtProvider,
                        requestBodies,
                        responses,
                        config
                ),
                responses,
                config
        );
        register(
                server,
                "/api/auth/check",
                new AuthCheckHandler(currentUserResolver, authService, responses),
                responses,
                config
        );
        register(
                server,
                "/api/profile",
                new ProfileHandler(
                        currentUserResolver,
                        profileService,
                        requestBodies,
                        responses
                ),
                responses,
                config
        );
        register(
                server,
                "/api/bids",
                new BidHandler(
                        currentUserResolver,
                        serviceKeys,
                        bidSummaryService,
                        bidDocumentService,
                        requestBodies,
                        responses
                ),
                responses,
                config
        );
        register(
                server,
                "/api/cache",
                new BidCacheHandler(
                        currentUserResolver,
                        serviceKeys,
                        bidCacheService,
                        requestBodies,
                        responses
                ),
                responses,
                config
        );
        register(
                server,
                "/api/health",
                new HealthHandler(connectionFactory, responses),
                responses,
                config
        );
        register(
                server,
                "/api/health/ready",
                new HealthHandler(connectionFactory, responses),
                responses,
                config
        );
        register(
                server,
                "/api/health/live",
                new LivenessHandler(responses),
                responses,
                config
        );

        // 기본 제공 로그인·회원가입 화면은 기존 주소를 그대로 유지합니다.
        register(
                server,
                "/login",
                new StaticResourceHandler(
                        "web/login.html",
                        "text/html; charset=utf-8",
                        responses
                ),
                responses,
                config
        );
        register(
                server,
                "/signup",
                new StaticResourceHandler(
                        "web/signup.html",
                        "text/html; charset=utf-8",
                        responses
                ),
                responses,
                config
        );
        register(
                server,
                "/static/style.css",
                new StaticResourceHandler(
                        "web/style.css",
                        "text/css; charset=utf-8",
                        responses
                ),
                responses,
                config
        );
        register(
                server,
                "/static/app.js",
                new StaticResourceHandler(
                        "web/app.js",
                        "application/javascript; charset=utf-8",
                        responses
                ),
                responses,
                config
        );
        register(
                server,
                "/",
                new RedirectHandler("/login", responses),
                responses,
                config
        );

        register(server, "/api/me/", new PipelineHandler(
                currentUserResolver, pipelineService, requestBodies, responses), responses, config);

        server.start();
        System.out.printf(
                "Workplace backend started at http://localhost:%d%n",
                config.serverPort()
        );
    }

    /** 모든 엔드포인트에 로깅, CORS, 공통 오류 처리를 같은 순서로 적용합니다. */
    private static void register(
            HttpServer server,
            String path,
            HttpHandler handler,
            HttpResponses responses,
            AppConfig config
    ) {
        HttpHandler wrapped = new RequestLoggingHandler(
                new CorsHandler(
                        new ErrorHandlingHandler(handler, responses),
                        responses,
                        config.allowedOrigins()
                )
        );
        server.createContext(path, wrapped);
    }
}
