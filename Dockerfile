FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    MIRROR_WORKSPACE=/app/mirror_output

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/mirror_output

EXPOSE 8000

CMD ["sh", "-c", "waitress-serve --port=${PORT:-8000} server:app"]
