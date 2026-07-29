# Build context is an ASSEMBLED directory, not this one - run assemble.sh first.
# See README.md for why the App cannot just build from the repo root.
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.18
FROM ${BUILD_FROM}

# Pinned minimal deps (pymodbus, PyYAML, aiomqtt). All ship musl wheels for the
# supported architectures, so no compiler is needed. If a future dependency
# lacks one, add a virtual build stage rather than carrying gcc in the final
# image:
#   RUN apk add --no-cache --virtual .build gcc musl-dev python3-dev \
#       && pip install --no-cache-dir -r /tmp/requirements.txt \
#       && apk del .build
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

WORKDIR /app
COPY heatctl/ /app/heatctl/
# Layer 2. Travels with the App but runs as its own process (run.sh), so
# that its failure cannot take the control core with it.
COPY optimizer/ /app/optimizer/

# Template only. The LIVE config lives in the App's config directory at
# /config/config.yaml so it survives image rebuilds and stays operator-editable.
# run.sh seeds it from here on first start and never overwrites it.
COPY config.dist.yaml /app/config.dist.yaml

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
