package workplace.repository;

import java.sql.Connection;
import java.sql.SQLException;

/** Repository가 JDBC 연결 생성 방식에 의존하지 않도록 추상화합니다. */
@FunctionalInterface
public interface ConnectionFactory {

    Connection open() throws SQLException;
}
