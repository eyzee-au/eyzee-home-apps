FROM python:3.13-alpine
LABEL io.hass.name="EyZEE Setup" io.hass.description="EyZEE Home onboarding" \
      io.hass.version="0.1.0-beta.1" io.hass.type="addon" io.hass.arch="aarch64|amd64"
WORKDIR /app
RUN pip install --no-cache-dir PyYAML==6.0.2 websocket-client==1.8.0
COPY . /app
EXPOSE 8099
CMD ["python", "/app/server.py"]
