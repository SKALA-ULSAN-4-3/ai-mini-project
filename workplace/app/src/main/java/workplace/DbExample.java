package workplace;

import java.sql.*;

public class DbExample {
    public static void main(String[] args) {
        // 예제 코드에도 비밀번호를 직접 작성하지 않고 실행 환경에서 받습니다.
        String url = System.getenv().getOrDefault(
                "DB_URL",
                "jdbc:mariadb://localhost:53301/sql_db"
        );
        String user = System.getenv().getOrDefault("DB_USER", "root");
        String pw = System.getenv("DB_PASSWORD");

        if (pw == null || pw.isBlank()) {
            throw new IllegalStateException("DB_PASSWORD 환경 변수가 필요합니다.");
        }

        String sql = "SHOW TABLES";

        try (Connection conn = DriverManager.getConnection(url, user, pw);
             PreparedStatement ps = conn.prepareStatement(sql);
             ResultSet rs = ps.executeQuery()) {

            System.out.println("=== TABLES ===");
            while (rs.next()) {
                System.out.println(rs.getString(1)); // 테이블명
            }

        } catch (SQLException e) {
            e.printStackTrace();
        }
    }
}

/* build.gradle 파일에 다음 설정을 추가, 이는 DbExample.java 예제 개별 실행을 위한 작업

tasks.register('runDbExample', JavaExec) {
    classpath = sourceSets.main.runtimeClasspath
    mainClass = 'workplace.DbExample'
}

이어서 다음 명령으로 실행

./gradlew :app:runDbExample

*/

