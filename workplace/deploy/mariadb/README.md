# Kubernetes MariaDB 배포

이 구성은 프로젝트의 MariaDB를 다음 형태로 설치합니다.

- MariaDB 11.4 단일 인스턴스
- 클러스터 내부 전용 `ClusterIP` 서비스
- 데이터 보존을 위한 5Gi PVC
- Kubernetes Secret 기반 비밀번호 관리
- `database/schema.sql` 최초 자동 적용
- `utf8mb4` 문자셋

## 1. 사전 확인

현재 연결된 클러스터와 기본 StorageClass를 확인합니다.

```bash
kubectl config current-context
kubectl get storageclass
```

기본 StorageClass가 없다면 `values.yaml`의 `global.storageClass`와
`primary.persistence.storageClass`에 실제 StorageClass 이름을 지정합니다.

## 2. 비밀번호 준비

예제 파일을 `.env`로 복사하고 값을 변경합니다.

```bash
cp deploy/mariadb/.env.example deploy/mariadb/.env
```

`.env`는 Git에서 제외됩니다. 실제 비밀번호가 들어 있는 `.env`는 공유하거나
커밋하지 않습니다.

## 3. 설치

`workplace` 폴더에서 실행합니다.

```bash
chmod +x deploy/mariadb/install.sh
./deploy/mariadb/install.sh
```

설치 스크립트가 다음 리소스를 생성합니다.

- Namespace: 기본값 `ai-mini-project`
- Secret: `ai-mini-mariadb-auth`
- 초기화 ConfigMap: `ai-mini-mariadb-init`
- Helm release 및 Service: `ai-mini-mariadb`
- MariaDB StatefulSet과 PVC

## 4. 백엔드 연결 정보

Java 백엔드가 같은 Namespace에 배포되면 다음 값을 사용합니다.

```env
DB_URL=jdbc:mariadb://ai-mini-mariadb:3306/sql_db
DB_USER=workplace_app
DB_PASSWORD=<ai-mini-mariadb-auth의 mariadb-password 값>
```

Java Deployment에서는 DB 비밀번호를 다음과 같이 주입합니다.

```yaml
env:
  - name: DB_URL
    value: jdbc:mariadb://ai-mini-mariadb:3306/sql_db
  - name: DB_USER
    value: workplace_app
  - name: DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: ai-mini-mariadb-auth
        key: mariadb-password
```

다른 Namespace에서 접속하면 전체 DNS를 사용합니다.

```text
jdbc:mariadb://ai-mini-mariadb.ai-mini-project.svc.cluster.local:3306/sql_db
```

## 5. 상태 확인

```bash
kubectl get pods,services,pvc -n ai-mini-project
kubectl logs -n ai-mini-project -l app.kubernetes.io/instance=ai-mini-mariadb
```

Pod는 `Running`, PVC는 `Bound` 상태여야 합니다.

## 6. 로컬 접속

DB를 인터넷에 공개하지 않고 필요할 때만 포트 포워딩합니다.

```bash
kubectl port-forward -n ai-mini-project service/ai-mini-mariadb 53301:3306
```

포트 포워딩이 실행되는 동안 로컬 Java 애플리케이션은 다음 주소를 사용합니다.

```env
DB_URL=jdbc:mariadb://localhost:53301/sql_db
```

## 주의 사항

- 초기화 SQL은 빈 PVC의 최초 기동에서만 실행됩니다.
- `schema.sql` 변경 사항은 기존 DB에 자동 적용되지 않습니다.
- Helm release를 제거해도 PVC가 남을 수 있습니다.
- PVC를 삭제하면 저장된 회원 정보가 사라질 수 있으므로 먼저 백업해야 합니다.
- 운영 중 스키마 변경은 Flyway 또는 별도의 마이그레이션 Job을 사용하는 것이
  안전합니다.
