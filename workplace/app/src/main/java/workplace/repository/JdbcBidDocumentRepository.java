package workplace.repository;

import workplace.domain.BidDocument;
import workplace.exception.ConflictException;
import workplace.exception.ServiceUnavailableException;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;

/** 공고 원본 PDF 메타데이터의 저장과 조회 SQL을 한곳에서 관리합니다. */
public final class JdbcBidDocumentRepository implements BidDocumentRepository {

    private static final String UNIQUE_VIOLATION = "23505";
    private static final String COLUMNS =
            "id, bid_no, revision, file_name, storage_key, size_bytes, "
                    + "source_url, collected_at";

    private final ConnectionFactory connectionFactory;

    public JdbcBidDocumentRepository(ConnectionFactory connectionFactory) {
        this.connectionFactory = connectionFactory;
    }

    @Override
    public boolean exists(String bidNo, String revision, String fileName) {
        String sql = "SELECT 1 FROM bid_documents "
                + "WHERE bid_no = ? AND revision = ? AND file_name = ?";

        try (Connection connection = connectionFactory.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, bidNo);
            statement.setString(2, revision);
            statement.setString(3, fileName);

            try (ResultSet result = statement.executeQuery()) {
                return result.next();
            }
        } catch (SQLException exception) {
            throw new ServiceUnavailableException("문서 정보를 조회할 수 없습니다.", exception);
        }
    }

    @Override
    public BidDocument save(
            String bidNo,
            String revision,
            String fileName,
            String storageKey,
            long sizeBytes,
            String sourceUrl
    ) {
        String sql = "INSERT INTO bid_documents "
                + "(bid_no, revision, file_name, storage_key, size_bytes, source_url) "
                + "VALUES (?, ?, ?, ?, ?, ?) RETURNING " + COLUMNS;

        try (Connection connection = connectionFactory.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, bidNo);
            statement.setString(2, revision);
            statement.setString(3, fileName);
            statement.setString(4, storageKey);
            statement.setLong(5, sizeBytes);
            statement.setString(6, sourceUrl);

            try (ResultSet result = statement.executeQuery()) {
                result.next();
                return toDocument(result);
            }
        } catch (SQLException exception) {
            if (UNIQUE_VIOLATION.equals(exception.getSQLState())) {
                throw new ConflictException("이미 등록된 파일명입니다.");
            }
            throw new ServiceUnavailableException("문서 정보를 저장할 수 없습니다.", exception);
        }
    }

    @Override
    public List<BidDocument> findByBid(String bidNo, String revision) {
        String sql = "SELECT " + COLUMNS + " FROM bid_documents WHERE bid_no = ? "
                + (revision == null ? "" : "AND revision = ? ")
                + "ORDER BY revision, id";

        try (Connection connection = connectionFactory.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, bidNo);
            if (revision != null) {
                statement.setString(2, revision);
            }

            try (ResultSet result = statement.executeQuery()) {
                List<BidDocument> documents = new ArrayList<>();
                while (result.next()) {
                    documents.add(toDocument(result));
                }
                return documents;
            }
        } catch (SQLException exception) {
            throw new ServiceUnavailableException("문서 목록을 조회할 수 없습니다.", exception);
        }
    }

    private BidDocument toDocument(ResultSet result) throws SQLException {
        return new BidDocument(
                result.getLong("id"),
                result.getString("bid_no"),
                result.getString("revision"),
                result.getString("file_name"),
                result.getString("storage_key"),
                result.getLong("size_bytes"),
                result.getString("source_url"),
                result.getTimestamp("collected_at").toInstant()
        );
    }
}
