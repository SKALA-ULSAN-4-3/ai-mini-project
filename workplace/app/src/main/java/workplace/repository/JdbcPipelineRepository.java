package workplace.repository;

import workplace.domain.PipelineEntry;
import workplace.exception.ServiceUnavailableException;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/** JDBC 저장소: 원자적 SQL, 중복 방지, 상태 역행 방지. */
public final class JdbcPipelineRepository implements PipelineRepository {
    private static final String COLUMNS = "bid_no, revision, status, selected_at, approved_at";
    private final ConnectionFactory connections;

    public JdbcPipelineRepository(ConnectionFactory connections) {
        this.connections = connections;
    }

    @Override
    public PipelineEntry select(String user, String bidNo, String revision) {
        // 멱등성: 최초 처리 시각과 기존 승인 상태 보존.
        String sql = """
                INSERT INTO user_bid_pipeline (business_registration_number, bid_no, revision)
                VALUES (?, ?, ?)
                ON CONFLICT (business_registration_number, bid_no, revision)
                DO UPDATE SET bid_no = EXCLUDED.bid_no
                RETURNING
                """ + COLUMNS;
        return mutate(sql, user, bidNo, revision).orElseThrow();
    }

    @Override
    public Optional<PipelineEntry> approve(String user, String bidNo, String revision) {
        // 멱등성: 최초 처리 시각과 기존 승인 상태 보존.
        String sql = """
                UPDATE user_bid_pipeline SET
                    status = 'approved',
                    approved_at = COALESCE(approved_at, CURRENT_TIMESTAMP),
                    updated_at = CASE WHEN status = 'selected'
                        THEN CURRENT_TIMESTAMP ELSE updated_at END
                WHERE business_registration_number = ? AND bid_no = ? AND revision = ?
                RETURNING
                """ + COLUMNS;
        return mutate(sql, user, bidNo, revision);
    }

    private Optional<PipelineEntry> mutate(String sql, String user, String bidNo, String revision) {
        try (Connection connection = connections.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, user);
            statement.setString(2, bidNo);
            statement.setString(3, revision);
            try (ResultSet result = statement.executeQuery()) {
                return result.next() ? Optional.of(read(result)) : Optional.empty();
            }
        } catch (SQLException exception) {
            throw new ServiceUnavailableException("진행 상태를 처리할 수 없습니다.", exception);
        }
    }

    @Override
    public List<PipelineEntry> findAll(String user) {
        String sql = "SELECT " + COLUMNS + " FROM user_bid_pipeline "
                + "WHERE business_registration_number = ? ORDER BY selected_at DESC, bid_no, revision";
        try (Connection connection = connections.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, user);
            try (ResultSet result = statement.executeQuery()) {
                List<PipelineEntry> entries = new ArrayList<>();
                while (result.next()) {
                    entries.add(read(result));
                }
                return entries;
            }
        } catch (SQLException exception) {
            throw new ServiceUnavailableException("진행 상태를 처리할 수 없습니다.", exception);
        }
    }

    private PipelineEntry read(ResultSet result) throws SQLException {
        Timestamp approvedAt = result.getTimestamp("approved_at");
        return new PipelineEntry(result.getString("bid_no"), result.getString("revision"),
                result.getString("status"), result.getTimestamp("selected_at").toInstant(),
                approvedAt == null ? null : approvedAt.toInstant());
    }
}
