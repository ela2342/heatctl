#!/usr/bin/env bash
# Assemble a self-contained Home Assistant App (add-on) directory.
#
# Why this exists: an App's Docker build context is its own directory, so the
# App needs heatctl/ and requirements.txt inside it. The App also cannot simply
# live at the repository root, because HA requires its manifest to be named
# config.yaml - and that name is already taken by heatctl's own configuration.
# Rather than duplicate the sources in git, they are staged here on demand.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "${here}/../.." && pwd)"
out="${1:-${root}/dist/ha-addon}"

rm -rf "${out}"
mkdir -p "${out}"

# App-specific files
cp "${here}/config.yaml" "${here}/build.yaml" "${here}/Dockerfile" \
   "${here}/run.sh" "${out}/"
if [ -d "${here}/translations" ]; then
    cp -r "${here}/translations" "${out}/translations"
fi

# Sources and pinned dependencies
cp "${root}/requirements.txt" "${out}/requirements.txt"
cp -r "${root}/heatctl" "${out}/heatctl"

# heatctl's own config ships as a TEMPLATE. run.sh copies it into the App's
# config directory on first start; it is never the live file.
cp "${root}/config.yaml" "${out}/config.dist.yaml"
# Layer 2 travels with the App but runs as its own process (see run.sh).
cp -r "${root}/optimizer" "${out}/optimizer"

find "${out}" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "${out}" -name '*.pyc' -delete 2>/dev/null || true

echo "Assembled App in: ${out}"
echo
echo "Install on the HA host:"
echo "  scp -r '${out}' root@<ha-host>:/addons/heatctl"
echo "then in HA: Settings > Apps > Add-on Store > (3 dots) > Check for updates"
