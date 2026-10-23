package workplace.repository;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import workplace.domain.CompanyProfile;
import workplace.domain.CompanyProfileRequest;
import workplace.exception.ServiceUnavailableException;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/** 회사 프로필의 조회와 UPSERT SQL을 한곳에서 관리합니다. */
public final class JdbcCompanyProfileRepository implements CompanyProfileRepository {

    private static final TypeReference<List<String>> STRING_LIST_TYPE =
            new TypeReference<>() { };
    private static final TypeReference<List<Map<String, Object>>> MAP_LIST_TYPE =
            new TypeReference<>() { };

    private final ConnectionFactory connectionFactory;
    private final ObjectMapper objectMapper;

    public JdbcCompanyProfileRepository(
            ConnectionFactory connectionFactory,
            ObjectMapper objectMapper
    ) {
        this.connectionFactory = connectionFactory;
        this.objectMapper = objectMapper;
    }

    @Override
    public Optional<CompanyProfile> findByBusinessRegistrationNumber(
            String businessRegistrationNumber
    ) {
        String sql = """
                SELECT id, business_registration_number, industry, licenses,
                       region, company_size,
                       certs, credit_rating, track_records, owned_docs,
                       budget_min, budget_max, keywords, created_at, updated_at
                  FROM company_profiles
                 WHERE business_registration_number = ?
                """;

        try (Connection connection = connectionFactory.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, businessRegistrationNumber);

            try (ResultSet result = statement.executeQuery()) {
                return result.next()
                        ? Optional.of(toProfile(result))
                        : Optional.empty();
            }
        } catch (SQLException | JsonProcessingException exception) {
            throw unavailable("회사 프로필을 조회할 수 없습니다.", exception);
        }
    }

    @Override
    public CompanyProfile save(
            String businessRegistrationNumber,
            CompanyProfileRequest request
    ) {
        String sql = """
                INSERT INTO company_profiles (
                    business_registration_number, industry, licenses, region,
                    company_size, certs,
                    credit_rating, track_records, owned_docs,
                    budget_min, budget_max, keywords
                ) VALUES (
                    ?, ?, CAST(? AS jsonb), ?, ?, CAST(? AS jsonb), ?,
                    CAST(? AS jsonb), CAST(? AS jsonb), ?, ?, CAST(? AS jsonb)
                )
                ON CONFLICT (business_registration_number) DO UPDATE SET
                    industry = EXCLUDED.industry,
                    licenses = EXCLUDED.licenses,
                    region = EXCLUDED.region,
                    company_size = EXCLUDED.company_size,
                    certs = EXCLUDED.certs,
                    credit_rating = EXCLUDED.credit_rating,
                    track_records = EXCLUDED.track_records,
                    owned_docs = EXCLUDED.owned_docs,
                    budget_min = EXCLUDED.budget_min,
                    budget_max = EXCLUDED.budget_max,
                    keywords = EXCLUDED.keywords,
                    updated_at = CURRENT_TIMESTAMP
                """;

        try (Connection connection = connectionFactory.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            bind(statement, businessRegistrationNumber, request);
            statement.executeUpdate();
        } catch (SQLException | JsonProcessingException exception) {
            throw unavailable("회사 프로필을 저장할 수 없습니다.", exception);
        }

        // UPSERT 연결이 닫힌 뒤 조회하므로 불필요하게 두 JDBC 연결을 동시에
        // 점유하지 않습니다.
        return findByBusinessRegistrationNumber(businessRegistrationNumber)
                .orElseThrow(() -> unavailable(
                "저장된 회사 프로필을 다시 조회할 수 없습니다.",
                null
        ));
    }

    private void bind(
            PreparedStatement statement,
            String businessRegistrationNumber,
            CompanyProfileRequest request
    ) throws SQLException, JsonProcessingException {
        statement.setString(1, businessRegistrationNumber);
        statement.setString(2, request.industry());
        statement.setString(3, json(request.licenses()));
        statement.setString(4, request.region());
        statement.setString(5, request.companySize());
        statement.setString(6, json(request.certs()));
        statement.setString(7, request.creditRating());
        statement.setString(8, json(request.trackRecords()));
        statement.setString(9, json(request.ownedDocs()));
        setNullableLong(statement, 10, request.budgetMin());
        setNullableLong(statement, 11, request.budgetMax());
        statement.setString(12, json(request.keywords()));
    }

    private CompanyProfile toProfile(ResultSet result)
            throws SQLException, JsonProcessingException {
        Timestamp createdAt = result.getTimestamp("created_at");
        Timestamp updatedAt = result.getTimestamp("updated_at");

        return new CompanyProfile(
                result.getLong("id"),
                result.getString("business_registration_number"),
                result.getString("industry"),
                read(result, "licenses", STRING_LIST_TYPE),
                result.getString("region"),
                result.getString("company_size"),
                read(result, "certs", STRING_LIST_TYPE),
                result.getString("credit_rating"),
                read(result, "track_records", MAP_LIST_TYPE),
                read(result, "owned_docs", STRING_LIST_TYPE),
                nullableLong(result, "budget_min"),
                nullableLong(result, "budget_max"),
                read(result, "keywords", STRING_LIST_TYPE),
                createdAt.toInstant(),
                updatedAt.toInstant()
        );
    }

    /** null은 JSON "null"이 아닌 SQL NULL로 저장해 "모름"과 "없음([])"을 구분합니다. */
    private String json(Object value) throws JsonProcessingException {
        return value == null ? null : objectMapper.writeValueAsString(value);
    }

    private <T> T read(ResultSet result, String column, TypeReference<T> type)
            throws SQLException, JsonProcessingException {
        String value = result.getString(column);
        return value == null ? null : objectMapper.readValue(value, type);
    }

    private void setNullableLong(PreparedStatement statement, int index, Long value)
            throws SQLException {
        if (value == null) {
            statement.setNull(index, java.sql.Types.BIGINT);
        } else {
            statement.setLong(index, value);
        }
    }

    private Long nullableLong(ResultSet result, String column) throws SQLException {
        long value = result.getLong(column);
        return result.wasNull() ? null : value;
    }

    private ServiceUnavailableException unavailable(String message, Throwable cause) {
        return new ServiceUnavailableException(message, cause);
    }
}
