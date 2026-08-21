# Build context is an ASSEMBLED directory - run assemble.sh first.
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.18
FROM ${BUILD_FROM}

# aiomqtt only. The InfluxDB write path is stdlib urllib on purpose: one HTTP
# POST every few seconds does not justify a dependency, and the project's
# pinned set stays at three libraries.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

WORKDIR /app
COPY mqtt2influx/ /app/mqtt2influx/
COPY run.sh /run.sh
RUN chmod a+x /run.sh
CMD [ "/run.sh" ]
