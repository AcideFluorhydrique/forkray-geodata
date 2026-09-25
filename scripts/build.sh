#!/bin/bash
# Build geosite.dat, geoip.dat and geoip-only-cn-private.dat from data/ into
# out/, then check them. Needs Go and Python 3 and nothing from the network
# except the Go modules pinned in tools/go.sum.
#
# The output is a function of this repository's commit alone: the same
# checkout gives byte-identical files, which the build workflow verifies.

set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf out
mkdir -p out

go -C tools build -trimpath -o ../out/.bin/ \
  github.com/v2fly/domain-list-community \
  github.com/Loyalsoldier/geoip

out/.bin/domain-list-community \
  -datapath ./data/geosite \
  -outputdir ./out \
  -outputname geosite.dat

out/.bin/geoip convert -c ./config/geoip.json

rm -rf out/.bin
python3 scripts/check-dat.py out
(cd out && sha256sum -- *.dat | tee SHA256SUMS)
