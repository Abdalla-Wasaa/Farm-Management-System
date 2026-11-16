FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock "setuptools>=75"
COPY app ./app
RUN pip install --no-cache-dir --no-deps --no-build-isolation .
COPY migrations ./migrations
COPY alembic.ini ./
USER 10001:10001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
