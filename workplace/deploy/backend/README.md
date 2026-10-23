# Java 백엔드 Kubernetes 배포

## 1. 이미지 빌드

`workplace` 폴더에서 실행합니다.

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag <Registry주소>/workplace-backend:<태그> \
  --push \
  .
```

교육용 클러스터가 접근할 수 있는 Registry를 사용해야 합니다. 비공개
Registry라면 Namespace에 `imagePullSecret`도 준비해야 합니다.
멀티 플랫폼 빌드이므로 Apple Silicon 개발 환경과 일반적인 AMD64 Kubernetes
노드에서 같은 이미지 태그를 사용할 수 있습니다.

## 2. 배포 설정

```bash
cp deploy/backend/.env.example deploy/backend/.env
```

`.env`에서 다음 값을 실제 환경에 맞게 변경합니다.

- `K8S_NAMESPACE`: 허용받은 교육용 Namespace
- `BACKEND_IMAGE`: Registry에 올린 실제 이미지 주소
- `MARIADB_SERVICE_NAME`: MariaDB Service 이름
- `CORS_ORIGINS`: 배포된 프론트엔드 Origin
- `JWT_SECRET`: 새로 생성한 충분히 긴 무작위 값

`.env`는 Git에서 제외됩니다.

## 3. 선행 조건

동일한 Namespace에 다음 MariaDB 리소스가 먼저 있어야 합니다.

- Service: 기본값 `ai-mini-mariadb`
- Secret: `ai-mini-mariadb-auth`
- Secret 키: `mariadb-password`
- DB 사용자: `workplace_app`
- DB 이름: `sql_db`

권한은 배포 전에 확인합니다.

```bash
kubectl auth can-i create deployments -n class-4
kubectl auth can-i create services -n class-4
kubectl auth can-i create secrets -n class-4
kubectl auth can-i create configmaps -n class-4
```

## 4. 설치

```bash
chmod +x deploy/backend/install.sh
./deploy/backend/install.sh
```

백엔드는 `ClusterIP`로 설치됩니다. 외부 프론트엔드가 호출하려면 팀의
공통 Ingress 또는 Gateway에서 `workplace-backend:8080`으로 경로를 연결해야
합니다.

## 상태 점검

```bash
kubectl get pods,service -n class-4 -l app.kubernetes.io/name=workplace-backend
kubectl logs -n class-4 deployment/workplace-backend
kubectl port-forward -n class-4 service/workplace-backend 8080:8080
```

포트 포워딩 후 다음 주소로 준비 상태를 확인합니다.

```bash
curl http://localhost:8080/api/health/live
curl http://localhost:8080/api/health/ready
```
