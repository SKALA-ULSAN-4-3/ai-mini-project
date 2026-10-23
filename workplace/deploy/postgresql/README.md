# Aiven PostgreSQL 무료 DB 연결

백엔드는 로컬 PostgreSQL과 Aiven PostgreSQL에서 동일한 스키마와 JDBC 코드를
사용합니다. Aiven 비밀번호와 CA 인증서는 저장소에 커밋하지 않습니다.

## 1. 무료 서비스 생성

1. Aiven Console에서 프로젝트를 만듭니다.
2. `Create service`에서 `PostgreSQL`을 선택합니다.
3. 서비스 플랜은 반드시 `$0/month`로 표시되는 `Free`를 선택합니다.
4. 서비스가 `Running` 상태가 될 때까지 기다립니다.

무료 플랜이 아닌 `Developer`나 체험판을 선택하면 무료 기간 종료 후 비용이
발생할 수 있으므로 생성 전 요금 요약을 확인합니다.

## 2. 접속 정보 확인

서비스의 `Overview > Connection information`에서 다음 값을 확인합니다.

- Host
- Port
- User
- Password
- Database name (`defaultdb`가 일반적인 기본값입니다.)
- CA certificate

비밀번호는 팀 채팅이나 이슈에 붙이지 않고 백엔드 배포 서비스의 Secret
환경변수에만 입력합니다.

## 3. 스키마 적용

Aiven Console이 제공하는 `psql` 접속 명령에 `database/schema.sql`을 입력으로
전달합니다. 다음 명령은 구조 예시이며 Host와 Port 등은 Console 값으로
교체해야 합니다.

```bash
PGSSLMODE=require psql \
  --host='<Aiven Host>' \
  --port='<Aiven Port>' \
  --username='<Aiven User>' \
  --dbname='<Aiven Database>' \
  --password \
  --file=database/schema.sql
```

`--password` 프롬프트에서 입력하면 터미널 명령 기록에 비밀번호가 남지 않습니다.

## 4. 백엔드 환경변수

```env
DB_URL=jdbc:postgresql://<Host>:<Port>/<Database>?sslmode=require
DB_USER=<User>
DB_PASSWORD=<Password>
```

운영 연결에서는 Aiven이 제공하는 CA 인증서를 사용해 서버 인증까지 검증하는
`verify-full` 설정을 권장합니다. CA 파일을 컨테이너 Secret으로 마운트했다면
다음과 같이 연결할 수 있습니다.

```env
DB_URL=jdbc:postgresql://<Host>:<Port>/<Database>?sslmode=verify-full&sslrootcert=/run/secrets/aiven-ca.pem
```

## 5. 보안 원칙

- 프론트엔드는 DB에 직접 접속하지 않고 백엔드 API만 호출합니다.
- DB 비밀번호와 CA 파일은 Git에 커밋하지 않습니다.
- Aiven Console에서 유료 플랜으로 업그레이드하지 않습니다.
- 무료 DB는 교육·개발용이므로 중요한 데이터는 별도로 백업합니다.
