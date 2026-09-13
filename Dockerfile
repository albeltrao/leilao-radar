# Build do frontend
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Aplicação
FROM python:3.11-slim
WORKDIR /app

# poppler-utils e tesseract só são necessários com RADAR_OCR_HABILITADO=1.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ ./backend/
RUN pip install --no-cache-dir -e "./backend[postgres,redis,ocr]"

COPY --from=frontend /frontend/dist ./frontend/dist

ENV RADAR_DIRETORIO_RAW=/app/data/raw \
    RADAR_DIRETORIO_DOCUMENTOS=/app/data/docs \
    RADAR_DIRETORIO_FRONTEND=/app/frontend/dist

EXPOSE 8000
CMD ["uvicorn", "radar.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
