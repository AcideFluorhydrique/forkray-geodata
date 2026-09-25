# forkray-geodata

The routing databases (`geosite.dat`, `geoip.dat`, `geoip-only-cn-private.dat`)
for [Forkray](https://github.com/AcideFluorhydrique/v2rayNG), built only from
freely licensed sources and reproducible from this repository alone.

Every input is stored here as plain text under `data/`, so the files can be
rebuilt from a checkout with no network access beyond the Go modules pinned in
`tools/go.sum`. Two builds of the same commit produce byte-identical files; CI
checks this on every push.

## Why

v2rayNG embeds geo databases downloaded as prebuilt binaries at build time.
F-Droid does not accept that, and part of the usual data (MaxMind GeoLite2)
needs an account and a licence key to download. This repository replaces them
with data anyone can fetch, read, rebuild and verify.

## Sources

| Data | Source | License |
|---|---|---|
| geosite lists | [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) `data/`, copied as-is | MIT |
| geosite `gfw` | [gfwlist/gfwlist](https://github.com/gfwlist/gfwlist), converted to plain domains | LGPL-2.1 |
| geoip `cn` | [gaoyifan/china-operator-ip](https://github.com/gaoyifan/china-operator-ip) (`ip-lists` branch), ranges announced by Chinese operators over BGP | MIT |
| geoip countries (all others) | [DB-IP IP to Country Lite](https://db-ip.com/db/download/ip-to-country-lite) | CC BY 4.0 |
| geoip service lists (`google`, `facebook`, `fastly`, `netflix`, `telegram`, `twitter`, `cloudflare`, `cloudfront`) | Ranges each operator publishes (below), plus the prefixes of its ASNs (`config/asn.json`) from [DB-IP IP to ASN Lite](https://db-ip.com/db/download/ip-to-asn-lite) | CC BY 4.0 for the ASN data |
| geoip `private` | Reserved address blocks, built into the generator | — |

Published ranges: Google [goog.json](https://www.gstatic.com/ipranges/goog.json)
and [cloud.json](https://www.gstatic.com/ipranges/cloud.json), Telegram
[cidr.txt](https://core.telegram.org/resources/cidr.txt), Fastly
[public-ip-list](https://api.fastly.com/public-ip-list), Cloudflare
[ips-v4](https://www.cloudflare.com/ips-v4)/[ips-v6](https://www.cloudflare.com/ips-v6)
and AWS [ip-ranges.json](https://ip-ranges.amazonaws.com/ip-ranges.json)
(CloudFront only). These are address lists the operators publish for others to
route and filter by.

`sources.lock.json` records the exact commit, release and SHA-256 of
everything the current data was taken from. The license texts are in
`LICENSES/`.

**Attribution.** DB-IP's licence requires crediting it wherever the data is
used, and the MIT and LGPL licences require their notices to accompany the
data: an app shipping these files has to show them, including "IP Geolocation
by [DB-IP](https://db-ip.com)". `scripts/build.sh` writes all of it to
`out/NOTICE.html`, and `python3 scripts/notice.py --append-to <page.html>`
inserts it into an existing licences page.

## Not included

- **MaxMind GeoLite2**: needs an account and a licence key, under an EULA.
- **Loyalsoldier's extended lists** (e.g. the extra domains in its `geosite:cn`
  from dnsmasq-china-list, whose licence is not stated): the data here covers
  less as a result. Users can still download those files themselves from the
  app, through their own proxy.

## Building

Needs Go (the version in `tools/go.mod` or newer) and Python 3.

```sh
bash scripts/build.sh
```

The files, their checksums (`SHA256SUMS`) and the notices (`NOTICE.html`)
are written to `out/`. CI shows the checksums on each run's summary page.
`scripts/check-dat.py` fails the build if a category listed in
`config/required.txt` is missing or empty: Xray refuses to start when a routing
rule names a category its database lacks.

## Updating

`.github/workflows/update.yml` runs `scripts/update-sources.py` every week and
opens a pull request with the changes, built and checked by
`.github/workflows/build.yml`. Review the diff, above all `data/geoip/cn.txt`
and `data/geosite/cn`, before merging. It moves the geosite generator to the
same domain-list-community commit as the data; the geoip generator
([Loyalsoldier/geoip](https://github.com/Loyalsoldier/geoip), GPL-3.0) is
updated by hand with `go -C tools get -tool github.com/Loyalsoldier/geoip@<commit>`.

For the pull request to trigger the build, add a `SYNC_TOKEN` repository
secret: a fine-grained personal access token for this repository with Contents
and Pull requests read and write.

## License

The scripts and configuration in this repository are GPL-3.0 (`LICENSE`). The
data under `data/` keeps the license of its source, listed above.
