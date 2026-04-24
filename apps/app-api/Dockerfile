FROM python:3.12-slim

WORKDIR /app

COPY apps/app-api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY apps/app-api/alembic.ini /app/alembic.ini
COPY apps/app-api/alembic /app/alembic
COPY apps/app-api/src /app/src
COPY data/kb_seed /app/data/kb_seed

EXPOSE 8000

CMD ["uvicorn", "src.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
