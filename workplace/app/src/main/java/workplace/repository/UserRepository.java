package workplace.repository;

import workplace.domain.User;
import workplace.domain.SignupRequest;

import java.util.Optional;

/** 사용자 저장소가 제공해야 하는 기능을 정의합니다. */
public interface UserRepository {

    Optional<User> findByBusinessRegistrationNumber(String businessRegistrationNumber);

    User save(SignupRequest request, String passwordHash);
}
