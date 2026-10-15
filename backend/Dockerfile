FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app
COPY backend/requirements.txt backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements.lock
COPY backend/ .
RUN DEBUG=true DJANGO_SECRET_KEY=build-only-placeholder DATABASE_URL=postgresql://billora:billora@localhost/billora DB_POOL_ENABLED=false python manage.py collectstatic --noinput
RUN useradd --create-home billora && chown -R billora:billora /app
USER billora
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi:application --config config/gunicorn.conf.py"]
