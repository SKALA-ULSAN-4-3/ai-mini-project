#!/usr/bin/env bash

# Java 백엔드의 ConfigMap, Secret, Deployment, Service를 현재 Kubernetes
# context에 설치합니다. 실제 비밀번호와 이미지 주소는 같은 폴더의 .env에서 읽습니다.
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "${SCRIPT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/.env"
  set +a
fi

readonly NAMESPACE="${K8S_NAMESPACE:-class-4}"
readonly MARIADB_SERVICE="${MARIADB_SERVICE_NAME:-ai-mini-mariadb}"
readonly JWT_ISSUER_VALUE="${JWT_ISSUER:-simple-auth-server}"
readonly JWT_EXPIRATION_VALUE="${JWT_EXPIRATION_SECONDS:-3600}"
readonly CORS_ORIGINS_VALUE="${CORS_ORIGINS:-http://localhost:5174,http://localhost:8008}"

: "${BACKEND_IMAGE:?BACKEND_IMAGE 값이 필요합니다.}"
: "${JWT_SECRET:?JWT_SECRET 값이 필요합니다.}"

if [[ "${BACKEND_IMAGE}" == CHANGE_ME/* ]]; then
  echo "BACKEND_IMAGE를 실제 Registry 이미지 주소로 변경해 주세요." >&2
  exit 1
fi

for command_name in kubectl base64; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "필수 명령을 찾을 수 없습니다: ${command_name}" >&2
    exit 1
  fi
done

echo "Kubernetes context: $(kubectl config current-context)"
echo "Namespace: ${NAMESPACE}"
echo "Backend image: ${BACKEND_IMAGE}"

# 교육용 클러스터에서 Namespace 생성 권한이 없을 수 있으므로, 백엔드 설치
# 스크립트는 기존 Namespace가 존재하는지 확인만 하고 임의로 생성하지 않습니다.
if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
  echo "Namespace를 찾을 수 없습니다: ${NAMESPACE}" >&2
  exit 1
fi

# 민감하지 않은 실행 설정은 ConfigMap으로 멱등하게 생성·갱신합니다.
kubectl create configmap workplace-backend-config \
  --namespace "${NAMESPACE}" \
  --from-literal="SERVER_PORT=8080" \
  --from-literal="DB_URL=jdbc:mariadb://${MARIADB_SERVICE}:3306/sql_db" \
  --from-literal="DB_USER=workplace_app" \
  --from-literal="JWT_ISSUER=${JWT_ISSUER_VALUE}" \
  --from-literal="JWT_EXPIRATION_SECONDS=${JWT_EXPIRATION_VALUE}" \
  --from-literal="CORS_ORIGINS=${CORS_ORIGINS_VALUE}" \
  --dry-run=client \
  --output yaml \
  | kubectl apply -f -

# JWT Secret을 명령 출력에 노출하지 않으면서 생성·갱신합니다.
jwt_secret_base64="$(printf '%s' "${JWT_SECRET}" | base64 | tr -d '\n')"
kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: workplace-backend-auth
  namespace: ${NAMESPACE}
type: Opaque
data:
  jwt-secret: ${jwt_secret_base64}
EOF

kubectl apply --namespace "${NAMESPACE}" --filename "${SCRIPT_DIR}/service.yaml"
kubectl apply --namespace "${NAMESPACE}" --filename "${SCRIPT_DIR}/deployment.yaml"
kubectl set image \
  --namespace "${NAMESPACE}" \
  deployment/workplace-backend \
  "backend=${BACKEND_IMAGE}"

kubectl rollout status \
  --namespace "${NAMESPACE}" \
  deployment/workplace-backend \
  --timeout 5m

kubectl get pods,services \
  --namespace "${NAMESPACE}" \
  --selector app.kubernetes.io/name=workplace-backend
