FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/local/cuda/targets/x86_64-linux/lib:${LD_LIBRARY_PATH}

ARG PADDLE_GPU_PACKAGE=paddlepaddle-gpu==2.6.2
ARG PADDLE_WHL_URL=https://www.paddlepaddle.org.cn/packages/stable/cu118/

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv ca-certificates \
      libglib2.0-0 libgl1 libsm6 libxext6 libxrender1 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/local/bin/python \
    && ln -sf /usr/bin/pip3 /usr/local/bin/pip

WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt
COPY backend/requirements-ocr.txt /tmp/requirements-ocr.txt

RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements-ocr.txt \
    && pip uninstall -y paddlepaddle paddlepaddle-gpu || true \
    && pip install --no-cache-dir ${PADDLE_GPU_PACKAGE} -f ${PADDLE_WHL_URL} \
    && pip install --no-cache-dir --force-reinstall numpy==1.26.4 opencv-python==4.6.0.66 \
    && python - <<'PY'
import ctypes
import numpy, cv2, paddle
print('numpy', numpy.__version__, 'cv2', cv2.__version__, 'paddle', paddle.__version__)
for lib in ("libcudnn.so.8", "libcublas.so.11", "libcublasLt.so.11", "libcudart.so.11.0"):
    ctypes.CDLL(lib)
print("build-time cuda user-space libraries linked OK")
try:
    ctypes.CDLL("libcuda.so.1")
    print("runtime driver library libcuda.so.1 is visible at build time")
except OSError:
    print("libcuda.so.1 not visible at build time (expected); it is injected at runtime by nvidia-container-runtime")
PY

COPY backend /app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
