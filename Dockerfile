FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ backend/
COPY --from=web /app/frontend/dist frontend/dist
ENV APAAR_VAR_DIR=/app/var
EXPOSE 8000
WORKDIR /app/backend
CMD ["sh", "-c", "python -m app.seed --reset && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
