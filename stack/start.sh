#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

compose() {
  docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.live-code.yml "$@"
}

install_deps_in_backend() {
  compose up -d backend
  compose exec -T backend /bin/bash -lc '
    set -euo pipefail
    pip install --no-cache-dir -r /app/requirements.txt
    if [ -f /app/requirements-ocr.txt ]; then
      pip install --no-cache-dir -r /app/requirements-ocr.txt
    fi
    if [ "${OCR_USE_GPU:-false}" = "true" ]; then
      PKG="${PADDLE_GPU_PACKAGE:-paddlepaddle-gpu==2.6.2}"
      URL="${PADDLE_WHL_URL:-https://www.paddlepaddle.org.cn/packages/stable/cu118/}"
      pip uninstall -y paddlepaddle paddlepaddle-gpu || true
      pip install --no-cache-dir "$PKG" -f "$URL"
    fi
    python - <<'"'"'PY'"'"'
import sys
print("python:", sys.version.split()[0])
for name in ("numpy", "cv2", "paddle"):
    try:
        mod = __import__(name)
        ver = getattr(mod, "__version__", "unknown")
        print(f"{name}: {ver}")
    except Exception as exc:
        print(f"{name}: import failed -> {exc}")
PY
  '
}

if [ $# -eq 0 ]; then
  set -- up -d
fi

case "${1:-}" in
  deps)
    shift || true
    install_deps_in_backend
    compose restart backend
    ;;
  check)
    compose exec -T backend /bin/bash -lc '
      python - <<'"'"'PY'"'"'
for name in ("numpy", "cv2", "paddle"):
    try:
        mod = __import__(name)
        ver = getattr(mod, "__version__", "unknown")
        print(f"{name}: {ver}")
    except Exception as exc:
        print(f"{name}: import failed -> {exc}")
PY
    '
    ;;
  *)
    compose "$@"
    ;;
esac
