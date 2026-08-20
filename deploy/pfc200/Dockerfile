# heatctl on the WAGO PFC200 750-8212. See docs/PFC200.md.
#
# WHY A CONTAINER AT ALL, on a project whose premise is boring technology:
# the device has no Python and no pip, only opkg against WAGO's feed, and a
# root filesystem with 88 MB free. There is no third option. `deploy/systemd`
# does not apply here.
#
# DEBIAN SLIM, NOT ALPINE, deliberately. PyYAML ships manylinux wheels but not
# musllinux for every release, so alpine risks pulling a compiler onto a
# single ARMv7 core to build a dependency that has a perfectly good wheel.
# Slim costs ~30 MB more on a 110 GB card.
#
# Pin by digest when you settle on a base - a tag is not a version, and this
# project has been bitten by that twice (requirements.txt, eclipse-mosquitto).
FROM python:3.12-slim

# Same three pinned deps as the App. Installed before the source is copied so
# a code change does not re-resolve them on a slow core.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

WORKDIR /app
COPY heatctl/ /app/heatctl/
COPY optimizer/ /app/optimizer/
COPY entrypoint.sh /entrypoint.sh
RUN chmod a+x /entrypoint.sh

# Config is MOUNTED, never baked. Same rule as the App: the operator's file is
# the source of truth for the register map and the safety limits, and an image
# rebuild must not be able to touch it.
CMD ["/entrypoint.sh"]
