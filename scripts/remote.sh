#!/usr/bin/env bash
# Wrapper SSH/rsync que lee credenciales desde .env (raíz del repo).
# La imagen Docker se construye en local y se transfiere al VPS por SSH.
#
# Uso:
#   ./scripts/remote.sh deploy          # build local → sube imagen + datos + .env → reinicia
#   ./scripts/remote.sh build           # solo construye la imagen en local
#   ./scripts/remote.sh push-image      # sube la imagen ya construida al VPS
#   ./scripts/remote.sh rsync           # sincroniza código y data/ al VPS
#   ./scripts/remote.sh restart         # sube .env y recrea el contenedor
#   ./scripts/remote.sh health          # GET API_BASE_URL/api/v1/health
#   ./scripts/remote.sh ssh 'hostname'  # comando remoto arbitrario
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "No existe .env en $ROOT" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

: "${SSH_HOST:?SSH_HOST no definido en .env}"
: "${SSH_USER:=root}"
: "${SSH_PORT:=22}"
: "${SSH_PASSWORD:?SSH_PASSWORD no definido en .env}"
: "${DEPLOY_PATH:=/opt/asistente-ia}"
: "${CONTAINER_NAME:=asistente-ia-educacion}"
: "${DOCKER_IMAGE:=asistente-ia_asistente:latest}"

SSHPASS_BIN="$(command -v sshpass || true)"
if [[ -z "$SSHPASS_BIN" ]]; then
  for c in /usr/local/bin/sshpass /opt/homebrew/bin/sshpass; do
    [[ -x "$c" ]] && SSHPASS_BIN="$c" && break
  done
fi
if [[ -z "$SSHPASS_BIN" ]]; then
  echo "Instala sshpass (brew install sshpass)" >&2
  exit 1
fi

export SSHPASS="$SSH_PASSWORD"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 -p "$SSH_PORT")

remote_ssh() {
  "$SSHPASS_BIN" -e ssh "${SSH_OPTS[@]}" "${SSH_USER}@${SSH_HOST}" "$@"
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker no está instalado o no está en PATH" >&2
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "Docker no responde. ¿Está Docker Desktop en ejecución?" >&2
    exit 1
  fi
}

build_image() {
  require_docker
  echo "==> Construyendo imagen local: ${DOCKER_IMAGE}"
  docker build -t "${DOCKER_IMAGE}" .
}

push_image() {
  require_docker
  if ! docker image inspect "${DOCKER_IMAGE}" >/dev/null 2>&1; then
    echo "No existe la imagen ${DOCKER_IMAGE}. Ejecuta: $0 build" >&2
    exit 1
  fi
  echo "==> Transfiriendo imagen ${DOCKER_IMAGE} a ${SSH_HOST} (puede tardar unos minutos)..."
  docker save "${DOCKER_IMAGE}" | remote_ssh "docker load"
  echo "==> Imagen cargada en el servidor"
}

rsync_project() {
  "$SSHPASS_BIN" -e rsync -az \
    --exclude '.venv' --exclude '.git' --exclude 'storage' --exclude '__pycache__' \
    --exclude '.DS_Store' --exclude '.cursor' --exclude 'docs/_pipeline_run_raw.json' \
    -e "ssh ${SSH_OPTS[*]}" \
    "$ROOT/" "${SSH_USER}@${SSH_HOST}:${DEPLOY_PATH}/"
}

upload_env() {
  "$SSHPASS_BIN" -e rsync -az -e "ssh ${SSH_OPTS[*]}" \
    "$ROOT/.env" "${SSH_USER}@${SSH_HOST}:${DEPLOY_PATH}/.env"
}

restart_container() {
  upload_env
  echo "==> Recreando contenedor ${CONTAINER_NAME} en ${SSH_HOST}..."
  remote_ssh "cd ${DEPLOY_PATH} && docker rm -f ${CONTAINER_NAME} 2>/dev/null || true; \
    set -a && . ./.env && set +a; \
    docker run -d --name ${CONTAINER_NAME} --restart unless-stopped --memory 700m \
      -p 8000:8000 \
      -e OPENAI_API_KEY -e LLM_MODEL -e EMBEDDING_MODEL \
      -e LANGCHAIN_TRACING_V2 -e LANGCHAIN_API_KEY -e LANGCHAIN_PROJECT \
      -e DATABASE_URL -e JWT_SECRET -e JWT_EXPIRE_MINUTES -e CORS_ORIGINS \
      -e LOG_LEVEL -e LOG_VERBOSE \
      -v ${DEPLOY_PATH}/data:/app/data:ro \
      -v asistente-ia_asistente_storage:/app/storage \
      ${DOCKER_IMAGE} && sleep 5 && curl -sS http://127.0.0.1:8000/api/v1/health"
}

cmd="${1:-}"
shift || true

case "$cmd" in
  ssh)
    remote_ssh "$@"
    ;;
  build)
    build_image
    ;;
  push-image)
    push_image
    ;;
  rsync)
    rsync_project
    ;;
  restart)
    restart_container
    ;;
  deploy)
    build_image
    rsync_project
    push_image
    restart_container
    echo ""
    echo "==> Despliegue completado. Comprueba: $0 health"
    ;;
  health)
    curl -sS "${API_BASE_URL:-http://${SSH_HOST}:8000}/api/v1/health"; echo
    ;;
  *)
    cat <<EOF
Uso: $0 <comando>

  deploy          Build local + rsync + push imagen + reinicia contenedor (flujo completo)
  build           Construye la imagen Docker en local
  push-image      Sube la imagen local al VPS (docker save | ssh docker load)
  rsync           Sincroniza el proyecto a DEPLOY_PATH (sin reconstruir imagen)
  restart         Sube .env y recrea el contenedor con la imagen ya presente en el VPS
  health          GET API_BASE_URL/api/v1/health
  ssh 'comando'   Ejecuta un comando remoto

Variables leídas de .env:
  SSH_HOST SSH_USER SSH_PORT SSH_PASSWORD DEPLOY_PATH CONTAINER_NAME
  DOCKER_IMAGE API_BASE_URL

Ejemplo de actualización tras cambiar código:
  ./scripts/remote.sh deploy
EOF
    exit 1
    ;;
esac
