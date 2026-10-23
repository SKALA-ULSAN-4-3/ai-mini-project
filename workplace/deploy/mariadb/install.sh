#!/usr/bin/env bash

# Kubernetes에 프로젝트용 MariaDB를 설치하거나 설정을 갱신합니다.
# 실제 비밀번호는 저장소에 남기지 않고 환경변수 또는 같은 폴더의 .env에서 읽습니다.
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly WORKPLACE_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
readonly VALUES_FILE="${SCRIPT_DIR}/values.yaml"
readonly SCHEMA_FILE="${WORKPLACE_DIR}/database/schema.sql"

# 개발자가 로컬에서만 관리하는 .env가 있으면 환경변수로 불러옵니다.
# .env 안의 특수문자를 안전하게 유지하려면 값을 작은따옴표로 감싸야 합니다.
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/.env"
  set +a
fi

readonly NAMESPACE="${K8S_NAMESPACE:-ai-mini-project}"
readonly RELEASE_NAME="${MARIADB_RELEASE_NAME:-ai-mini-mariadb}"
readonly SECRET_NAME="ai-mini-mariadb-auth"
readonly INIT_CONFIG_MAP_NAME="ai-mini-mariadb-init"
readonly CHART_VERSION="20.5.5"

# 빈 비밀번호로 MariaDB가 설치되는 일을 막기 위해 설치 전에 즉시 검사합니다.
: "${MARIADB_ROOT_PASSWORD:?MARIADB_ROOT_PASSWORD 값이 필요합니다.}"
: "${MARIADB_APP_PASSWORD:?MARIADB_APP_PASSWORD 값이 필요합니다.}"
: "${MARIADB_REPLICATION_PASSWORD:?MARIADB_REPLICATION_PASSWORD 값이 필요합니다.}"

for command_name in kubectl helm base64; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "필수 명령을 찾을 수 없습니다: ${command_name}" >&2
    exit 1
  fi
done

if [[ ! -f "${SCHEMA_FILE}" ]]; then
  echo "DB 스키마 파일을 찾을 수 없습니다: ${SCHEMA_FILE}" >&2
  exit 1
fi

# 현재 kubectl context가 올바른 클러스터인지 사용자가 확인할 수 있도록 표시합니다.
echo "Kubernetes context: $(kubectl config current-context)"
echo "Namespace: ${NAMESPACE}"
echo "MariaDB release: ${RELEASE_NAME}"

if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
  kubectl create namespace "${NAMESPACE}"
fi

# Secret 값을 출력하지 않으면서 멱등하게 생성·갱신합니다.
# Bitnami MariaDB Chart 20.5.5가 요구하는 세 가지 키를 모두 포함합니다.
root_password_base64="$(printf '%s' "${MARIADB_ROOT_PASSWORD}" | base64 | tr -d '\n')"
app_password_base64="$(printf '%s' "${MARIADB_APP_PASSWORD}" | base64 | tr -d '\n')"
replication_password_base64="$(
  printf '%s' "${MARIADB_REPLICATION_PASSWORD}" | base64 | tr -d '\n'
)"

kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ${SECRET_NAME}
  namespace: ${NAMESPACE}
type: Opaque
data:
  mariadb-root-password: ${root_password_base64}
  mariadb-password: ${app_password_base64}
  mariadb-replication-password: ${replication_password_base64}
EOF

# schema.sql을 초기화 ConfigMap으로 등록합니다. 기존 PVC에는 재실행되지 않으며,
# 운영 중 스키마 변경은 별도의 마이그레이션으로 처리해야 합니다.
kubectl create configmap "${INIT_CONFIG_MAP_NAME}" \
  --namespace "${NAMESPACE}" \
  --from-file="001-schema.sql=${SCHEMA_FILE}" \
  --dry-run=client \
  --output yaml \
  | kubectl apply -f -

helm repo add bitnami https://charts.bitnami.com/bitnami --force-update
helm repo update bitnami

helm upgrade --install "${RELEASE_NAME}" bitnami/mariadb \
  --namespace "${NAMESPACE}" \
  --version "${CHART_VERSION}" \
  --values "${VALUES_FILE}" \
  --wait \
  --timeout 10m

echo
echo "MariaDB 설치 상태"
kubectl get pods,services,persistentvolumeclaims \
  --namespace "${NAMESPACE}" \
  --selector "app.kubernetes.io/instance=${RELEASE_NAME}"

echo
echo "Java DB_URL (같은 namespace 기준):"
echo "jdbc:mariadb://${RELEASE_NAME}:3306/sql_db"
