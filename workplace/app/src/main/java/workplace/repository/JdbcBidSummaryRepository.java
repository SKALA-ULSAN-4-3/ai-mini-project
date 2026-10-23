package workplace.repository;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import workplace.domain.BidSummary;
import workplace.domain.BidSummaryRequest;
import workplace.exception.ServiceUnavailableException;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/** 공고 요약의 UPSERT와 조회 SQL을 한곳에서 관리합니다. */
public final class JdbcBidSummaryRepository implements BidSummaryRepository {

    private static final TypeReference<List<String>> STRING_LIST_TYPE =
            new TypeReference<>() { };
    private static final String COLUMNS =
            "business_registration_number, bid_no, revision, summary, missing, "
                    + "needs_review, handoff, "
                    + "latency_ms, created_at, updated_at";

    private final ConnectionFactory connectionFactory;
    private final ObjectMapper objectMapper;

    public JdbcBidSummaryRepository(
            ConnectionFactory connectionFactory,
            ObjectMapper objectMapper
    ) {
        this.connectionFactory = connectionFactory;
        this.objectMapper = objectMapper;
    }

    @Override
    public BidSummary save(
            String businessRegistrationNumber,
            BidSummaryRequest request
    ) {
        String sql = """
                INSERT INTO bid_summaries (
                    business_registration_number, bid_no, revision, summary,
                    missing, needs_review, handoff, latency_ms
                ) VALUES (?, ?, ?, CAST(? AS jsonb), CAST(? AS jsonb), ?, ?, ?)
                ON CONFLICT (business_registration_number, bid_no, revision)
                DO UPDATE SET
                    summary = EXCLUDED.summary,
                    missing = EXCLUDED.missing,
                    needs_review = EXCLUDED.needs_review,
                    handoff = EXCLUDED.handoff,
                    latency_ms = EXCLUDED.latency_ms,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING """ + " " + COLUMNS;

        try (Connection connection = connectionFactory.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, businessRegistrationNumber);
            statement.setString(2, request.bidNo());
            statement.setString(3, request.revision());
            statement.setString(4, objectMapper.writeValueAsString(request.summary()));
            statement.setString(5, objectMapper.writeValueAsString(request.missing()));
            statement.setBoolean(6, Boolean.TRUE.equals(request.needsReview()));
            statement.setBoolean(7, Boolean.TRUE.equals(request.handoff()));
            if (request.latencyMs() == null) {
                statement.setNull(8, Types.BIGINT);
            } else {
                statement.setLong(8, request.latencyMs());
            }

            try (ResultSet result = statement.executeQuery()) {
                result.next();
                return toSummary(result);
            }
        } catch (SQLException | JsonProcessingException exception) {
            throw new ServiceUnavailableException("공고 요약을 저장할 수 없습니다.", exception);
        }
    }

    @Override
    public Optional<BidSummary> find(
            String businessRegistrationNumber,
            String bidNo,
            String revision
    ) {
        return queryOne(
                "SELECT " + COLUMNS + " FROM bid_summaries "
                        + "WHERE business_registration_number = ? "
                        + "AND bid_no = ? AND revision = ?",
                businessRegistrationNumber,
                bidNo,
                revision
        );
    }

    @Override
    public Optional<BidSummary> findLatest(
            String businessRegistrationNumber,
            String bidNo
    ) {
        return queryOne(
                "SELECT " + COLUMNS + " FROM bid_summaries "
                        + "WHERE business_registration_number = ? AND bid_no = ? "
                        + "ORDER BY revision DESC LIMIT 1",
                businessRegistrationNumber,
                bidNo,
                null
        );
    }

    @Override
    public List<BidSummary> findAll(
            String businessRegistrationNumber,
            int limit,
            int offset
    ) {
        String sql = "SELECT " + COLUMNS
                + " FROM bid_summaries WHERE business_registration_number = ? "
                + "ORDER BY bid_no, revision LIMIT ? OFFSET ?";

        try (Connection connection = connectionFactory.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, businessRegistrationNumber);
            statement.setInt(2, limit);
            statement.setInt(3, offset);

            try (ResultSet result = statement.executeQuery()) {
                List<BidSummary> summaries = new ArrayList<>();
                while (result.next()) {
                    summaries.add(toSummary(result));
                }
                return summaries;
            }
        } catch (SQLException | JsonProcessingException exception) {
            throw new ServiceUnavailableException("공고 요약 목록을 조회할 수 없습니다.", exception);
        }
    }

    private Optional<BidSummary> queryOne(
            String sql,
            String businessRegistrationNumber,
            String bidNo,
            String revision
    ) {
        try (Connection connection = connectionFactory.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, businessRegistrationNumber);
            statement.setString(2, bidNo);
            if (revision != null) {
                statement.setString(3, revision);
            }

            try (ResultSet result = statement.executeQuery()) {
                return result.next()
                        ? Optional.of(toSummary(result))
                        : Optional.empty();
            }
        } catch (SQLException | JsonProcessingException exception) {
            throw new ServiceUnavailableException("공고 요약을 조회할 수 없습니다.", exception);
        }
    }

    private BidSummary toSummary(ResultSet result)
            throws SQLException, JsonProcessingException {
        long latency = result.getLong("latency_ms");
        Long latencyMs = result.wasNull() ? null : latency;

        return new BidSummary(
                result.getString("business_registration_number"),
                result.getString("bid_no"),
                result.getString("revision"),
                objectMapper.readTree(result.getString("summary")),
                objectMapper.readValue(result.getString("missing"), STRING_LIST_TYPE),
                result.getBoolean("needs_review"),
                result.getBoolean("handoff"),
                latencyMs,
                result.getTimestamp("created_at").toInstant(),
                result.getTimestamp("updated_at").toInstant()
        );
    }
}
