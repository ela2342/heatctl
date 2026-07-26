ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12
FROM $BUILD_FROM
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY heatctl/ heatctl/
COPY config.yaml /etc/heatctl/config.yaml
CMD ["python", "-m", "heatctl.main", "/etc/heatctl/config.yaml"]
