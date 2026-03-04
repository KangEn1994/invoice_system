FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG INSTALL_OCR=false

WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt
COPY backend/requirements-ocr.txt /tmp/requirements-ocr.txt

RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && if [ "$INSTALL_OCR" = "true" ]; then pip install --no-cache-dir -r /tmp/requirements-ocr.txt; fi

COPY backend /app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
