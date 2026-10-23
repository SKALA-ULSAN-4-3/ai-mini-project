package workplace.repository;

import workplace.domain.User;
import workplace.domain.SignupRequest;
import workplace.exception.ConflictException;
import workplace.exception.ServiceUnavailableException;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Optional;

/** PreparedStatement만 사용해 SQL 삽입 공격을 방지하는 사용자 저장소입니다. */
public final class JdbcUserRepository implements UserRepository {

    private final ConnectionFactory connectionFactory;

    public JdbcUserRepository(ConnectionFactory connectionFactory) {
        this.connectionFactory = connectionFactory;
    }

    @Override
    public Optional<User> findByBusinessRegistrationNumber(
            String businessRegistrationNumber
    ) {
        String sql = """
                SELECT business_registration_number, password, corporate_name,
                       head_office_address, business_type, business_item,
                       unit_taxpayer_applicable
                  FROM users
                 WHERE business_registration_number = ?
                """;

        try (Connection connection = connectionFactory.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, businessRegistrationNumber);

            try (ResultSet result = statement.executeQuery()) {
                if (!result.next()) {
                    return Optional.empty();
                }
                return Optional.of(new User(
                        result.getString("business_registration_number"),
                        result.getString("password"),
                        result.getString("corporate_name"),
                        result.getString("head_office_address"),
                        result.getString("business_type"),
                        result.getString("business_item"),
                        result.getString("unit_taxpayer_applicable")
                ));
            }
        } catch (SQLException exception) {
            throw unavailable("사용자 정보를 조회할 수 없습니다.", exception);
        }
    }

    @Override
    public User save(SignupRequest request, String passwordHash) {
        String sql = """
                INSERT INTO users (
                    business_registration_number, password, corporate_name,
                    head_office_address, business_type, business_item,
                    unit_taxpayer_applicable
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """;

        try (Connection connection = connectionFactory.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, request.businessRegistrationNumber());
            statement.setString(2, passwordHash);
            statement.setString(3, request.corporateName());
            statement.setString(4, request.headOfficeAddress());
            statement.setString(5, request.businessType());
            statement.setString(6, request.businessItem());
            statement.setString(7, request.unitTaxpayerApplicable());
            statement.executeUpdate();

            return new User(
                    request.businessRegistrationNumber(),
                    passwordHash,
                    request.corporateName(),
                    request.headOfficeAddress(),
                    request.businessType(),
                    request.businessItem(),
                    request.unitTaxpayerApplicable()
            );
        } catch (SQLException exception) {
            // PostgreSQL은 UNIQUE 위반을 SQLState 23505로 전달합니다. JDBC 구현
            // 클래스에 의존하지 않고 표준 SQLState로 판별해야 드라이버 변경에도
            // 저장소의 업무 오류 변환 규칙이 유지됩니다.
            if ("23505".equals(exception.getSQLState())) {
                throw new ConflictException("이미 가입된 사업자등록번호입니다.");
            }
            throw unavailable("사용자를 저장할 수 없습니다.", exception);
        }
    }

    private ServiceUnavailableException unavailable(String message, SQLException cause) {
        return new ServiceUnavailableException(message, cause);
    }
}
