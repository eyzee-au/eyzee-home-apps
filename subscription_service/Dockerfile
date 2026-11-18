FROM python:3.13-slim
WORKDIR /app
COPY subscription_service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home eyzee
COPY subscription_service /app/subscription_service
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "subscription_service.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
