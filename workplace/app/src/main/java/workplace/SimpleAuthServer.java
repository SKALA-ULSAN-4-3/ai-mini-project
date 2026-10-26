package workplace;

/**
 * 기존 실습 자료의 실행 클래스명을 사용하는 경우를 위한 호환 진입점입니다.
 *
 * <p>실제 서버 구성은 책임별 클래스를 조립하는 {@link WorkplaceApplication}에
 * 있습니다. 새로운 기능은 이 클래스에 추가하지 않습니다.</p>
 */
@Deprecated
public final class SimpleAuthServer {

    private SimpleAuthServer() {
        // 실행 전용 클래스이므로 인스턴스 생성을 막습니다.
    }

    public static void main(String[] args) throws Exception {
        WorkplaceApplication.main(args);
    }
}
