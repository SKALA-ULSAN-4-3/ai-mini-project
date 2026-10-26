package workplace.repository;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import workplace.domain.CachedResult;
import workplace.exception.ServiceUnavailableException;

import java.sql.Connection;
import java.sql.Date;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

/** PostgreSQL JSONB를 이용해 24시간 캐시를 조회·갱신합니다. */
public final class JdbcBidCacheRepository implements BidCacheRepository {

    private static final String RESULT_COLUMNS = "result, created_at, expires_at";

    private final ConnectionFactory connectionFactory;
    private final ObjectMapper objectMapper;

    public JdbcBidCacheRepository(
            ConnectionFactory connectionFactory,
            ObjectMapper objectMapper
    ) {
        this.connectionFactory = connectionFactory;
        this.objectMapper = objectMapper;
    }

    @Override
    public Optional<CachedResult> findSearch(
            String businessRegistrationNumber,
            String requestHash
    ) {
        String sql = "SELECT " + RESULT_COLUMNS + " FROM bid_search_cache "
                + "WHERE business_registration_number = ? AND request_hash = ? "
                + "AND expires_at > CURRENT_TIMESTAMP";

        try (Connection connection = connectionFactory.open()) {
            purgeExpired(connection);
            try (PreparedStatement statement = connection.prepareStatement(sql)) {
                statement.setString(1, businessRegistrationNumber);
                statement.setString(2, requestHash);
                return readOne(statement);
            }
        } catch (SQLException | JsonProcessingException exception) {
            throw unavailable("공고 검색 캐시를 조회할 수 없습니다.", exception);
        }
    }

    @Override
    public CachedResult saveSearch(
            String businessRegistrationNumber,
            String requestHash,
            LocalDate from,
            LocalDate to,
            List<String> queries,
            int limit,
            String profileFingerprint,
            JsonNode result
    ) {
        String sql = """
                INSERT INTO bid_search_cache (
                    business_registration_number, request_hash,
                    search_start_date, search_end_date, keywords,
                    result_limit, profile_fingerprint, result
                ) VALUES (?, ?, ?, ?, CAST(? AS jsonb), ?, ?, CAST(? AS jsonb))
                ON CONFLICT (business_registration_number, request_hash)
                DO UPDATE SET
                    search_start_date = EXCLUDED.search_start_date,
                    search_end_date = EXCLUDED.search_end_date,
                    keywords = EXCLUDED.keywords,
                    result_limit = EXCLUDED.result_limit,
                    profile_fingerprint = EXCLUDED.profile_fingerprint,
                    result = EXCLUDED.result,
                    created_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP,
                    expires_at = CURRENT_TIMESTAMP + INTERVAL '24 hours'
                RETURNING result, created_at, expires_at
                """;

        try (Connection connection = connectionFactory.open()) {
            purgeExpired(connection);
            try (PreparedStatement statement = connection.prepareStatement(sql)) {
                statement.setString(1, businessRegistrationNumber);
                statement.setString(2, requestHash);
                statement.setDate(3, Date.valueOf(from));
                statement.setDate(4, Date.valueOf(to));
                statement.setString(5, objectMapper.writeValueAsString(queries));
                statement.setInt(6, limit);
                statement.setString(7, profileFingerprint);
                statement.setString(8, objectMapper.writeValueAsString(result));
                return required(statement, "저장된 공고 검색 캐시를 읽을 수 없습니다.");
            }
        } catch (SQLException | JsonProcessingException exception) {
            throw unavailable("공고 검색 캐시를 저장할 수 없습니다.", exception);
        }
    }

    @Override
    public Optional<CachedResult> findRfp(String bidNo, String revision) {
        String sql = "SELECT " + RESULT_COLUMNS + " FROM bid_rfp_cache "
                + "WHERE bid_no = ? AND revision = ? "
                + "AND expires_at > CURRENT_TIMESTAMP";

        try (Connection connection = connectionFactory.open()) {
            purgeExpired(connection);
            try (PreparedStatement statement = connection.prepareStatement(sql)) {
                statement.setString(1, bidNo);
                statement.setString(2, revision);
                return readOne(statement);
            }
        } catch (SQLException | JsonProcessingException exception) {
            throw unavailable("제안요청서 캐시를 조회할 수 없습니다.", exception);
        }
    }

    @Override
    public CachedResult saveRfp(String bidNo, String revision, JsonNode result) {
        String sql = """
                INSERT INTO bid_rfp_cache (bid_no, revision, result)
                VALUES (?, ?, CAST(? AS jsonb))
                ON CONFLICT (bid_no, revision)
                DO UPDATE SET
                    result = EXCLUDED.result,
                    created_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP,
                    expires_at = CURRENT_TIMESTAMP + INTERVAL '24 hours'
                RETURNING result, created_at, expires_at
                """;

        try (Connection connection = connectionFactory.open()) {
            purgeExpired(connection);
            try (PreparedStatement statement = connection.prepareStatement(sql)) {
                statement.setString(1, bidNo);
                statement.setString(2, revision);
                statement.setString(3, objectMapper.writeValueAsString(result));
                return required(statement, "저장된 제안요청서 캐시를 읽을 수 없습니다.");
            }
        } catch (SQLException | JsonProcessingException exception) {
            throw unavailable("제안요청서 캐시를 저장할 수 없습니다.", exception);
        }
    }

    /** 만료 데이터는 조회에서 제외할 뿐 아니라 캐시 사용 시 즉시 물리 삭제합니다. */
    private void purgeExpired(Connection connection) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "SELECT purge_expired_bid_caches()"
        )) {
            statement.execute();
        }
    }

    private Optional<CachedResult> readOne(PreparedStatement statement)
            throws SQLException, JsonProcessingException {
        try (ResultSet result = statement.executeQuery()) {
            return result.next() ? Optional.of(toCachedResult(result)) : Optional.empty();
        }
    }

    private CachedResult required(PreparedStatement statement, String message)
            throws SQLException, JsonProcessingException {
        return readOne(statement).orElseThrow(() -> unavailable(message, null));
    }

    private CachedResult toCachedResult(ResultSet result)
            throws SQLException, JsonProcessingException {
        return new CachedResult(
                objectMapper.readTree(result.getString("result")),
                result.getTimestamp("created_at").toInstant(),
                result.getTimestamp("expires_at").toInstant()
        );
    }

    private ServiceUnavailableException unavailable(String message, Throwable cause) {
        return new ServiceUnavailableException(message, cause);
    }
}
