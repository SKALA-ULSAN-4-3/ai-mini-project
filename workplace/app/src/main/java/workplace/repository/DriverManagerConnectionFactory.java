package workplace.repository;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;

/** 환경 설정을 이용해 PostgreSQL JDBC 연결을 생성합니다. */
public final class DriverManagerConnectionFactory implements ConnectionFactory {

    private final String url;
    private final String username;
    private final String password;

    public DriverManagerConnectionFactory(String url, String username, String password) {
        this.url = url;
        this.username = username;
        this.password = password;
    }

    @Override
    public Connection open() throws SQLException {
        return DriverManager.getConnection(url, username, password);
    }
}
