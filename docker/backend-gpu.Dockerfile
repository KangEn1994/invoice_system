FROM nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG PADDLE_GPU_PACKAGE=paddlepaddle-gpu==2.6.2
ARG PADDLE_WHL_URL=https://www.paddlepaddle.org.cn/packages/stable/cu118/

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/local/bin/python \
    && ln -sf /usr/bin/pip3 /usr/local/bin/pip

WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt
COPY backend/requirements-ocr.txt /tmp/requirements-ocr.txt

RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir ${PADDLE_GPU_PACKAGE} -f ${PADDLE_WHL_URL} \
    && pip install --no-cache-dir -r /tmp/requirements-ocr.txt

COPY backend /app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
