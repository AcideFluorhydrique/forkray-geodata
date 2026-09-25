#!/usr/bin/env python3
"""Refresh data/ from the upstream sources and record what was taken.

Every input to the .dat files is stored in this repository as plain text, so a
build needs nothing but a checkout of it (and the Go generators pinned in
tools/go.mod). This script is the only step that goes to the network: it pulls
each source listed in README.md, converts it to text, and writes the exact
upstream revisions, releases and checksums to sources.lock.json. Run it from
the repository root; review the resulting diff like any other change.

Environment:
  GH_TOKEN    optional; raises GitHub's API rate limit when resolving commits
  DBIP_MONTH  optional YYYY-MM; defaults to the newest published release
"""

import base64
import csv
import datetime
import gzip
import hashlib
import io
import ipaddress
import json
import os
import re
import shutil
import sys
import tarfile
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEOSITE_DIR = os.path.join(ROOT, 'data', 'geosite')
GEOIP_DIR = os.path.join(ROOT, 'data', 'geoip')
LICENSES_DIR = os.path.join(ROOT, 'LICENSES')
LOCK_FILE = os.path.join(ROOT, 'sources.lock.json')

DLC_REPO = 'v2fly/domain-list-community'
GFWLIST_REPO = 'gfwlist/gfwlist'
CHINA_IP_REPO = 'gaoyifan/china-operator-ip'
CHINA_IP_BRANCH = 'ip-lists'

# Ranges each operator publishes for its own network. Plain facts, published so
# that others can route and filter by them.
PUBLISHED_RANGES = {
    'google': [
        ('google-json', 'https://www.gstatic.com/ipranges/goog.json'),
        ('google-json', 'https://www.gstatic.com/ipranges/cloud.json'),
    ],
    'telegram': [('text', 'https://core.telegram.org/resources/cidr.txt')],
    'fastly': [('fastly-json', 'https://api.fastly.com/public-ip-list')],
    'cloudflare': [
        ('text', 'https://www.cloudflare.com/ips-v4'),
        ('text', 'https://www.cloudflare.com/ips-v6'),
    ],
    'cloudfront': [('aws-cloudfront-json', 'https://ip-ranges.amazonaws.com/ip-ranges.json')],
}

USER_AGENT = 'forkray-geodata/1 (+https://github.com/AcideFluorhydrique/forkray-geodata)'


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def fetch(url, api=False):
    headers = {'User-Agent': USER_AGENT}
    if api:
        headers['Accept'] = 'application/vnd.github+json'
        if os.environ.get('GH_TOKEN'):
            headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def head_commit(repo, ref):
    info = json.loads(fetch(f'https://api.github.com/repos/{repo}/commits/{ref}', api=True))
    return info['sha']


def raw(repo, commit, path):
    return fetch(f'https://raw.githubusercontent.com/{repo}/{commit}/{path}')


def write_list(path, networks):
    """Write networks one per line, merged and in address order."""
    v4 = ipaddress.collapse_addresses(n for n in networks if n.version == 4)
    v6 = ipaddress.collapse_addresses(n for n in networks if n.version == 6)
    lines = [str(n) for n in v4] + [str(n) for n in v6]
    with open(path, 'w', encoding='utf-8', newline='\n') as fp:
        fp.write(''.join(line + '\n' for line in lines))
    return len(lines)


def parse_networks(text):
    out = []
    for line in text.splitlines():
        line = line.split('#', 1)[0].strip()
        if line:
            out.append(ipaddress.ip_network(line, strict=False))
    return out


def range_to_networks(first, last):
    return ipaddress.summarize_address_range(ipaddress.ip_address(first), ipaddress.ip_address(last))


# --- geosite -----------------------------------------------------------------

def update_dlc(lock):
    commit = head_commit(DLC_REPO, 'master')
    log(f'domain-list-community {commit}')
    tarball = fetch(f'https://codeload.github.com/{DLC_REPO}/tar.gz/{commit}')
    shutil.rmtree(GEOSITE_DIR, ignore_errors=True)
    os.makedirs(GEOSITE_DIR)
    count = 0
    with tarfile.open(fileobj=io.BytesIO(tarball), mode='r:gz') as tar:
        for member in tar.getmembers():
            parts = member.name.split('/')
            # <repo>-<commit>/data/<list>; the lists are flat files.
            if len(parts) == 3 and parts[1] == 'data' and member.isfile():
                name = parts[2]
                if not re.fullmatch(r'[a-z0-9!@._-]+', name):
                    raise SystemExit(f'unexpected list name in {DLC_REPO}: {name!r}')
                with open(os.path.join(GEOSITE_DIR, name), 'wb') as fp:
                    fp.write(tar.extractfile(member).read())
                count += 1
            elif len(parts) == 2 and parts[1] == 'LICENSE' and member.isfile():
                with open(os.path.join(LICENSES_DIR, 'MIT-domain-list-community.txt'), 'wb') as fp:
                    fp.write(tar.extractfile(member).read())
    log(f'  {count} lists')
    lock['domain-list-community'] = {
        'repository': f'https://github.com/{DLC_REPO}',
        'commit': commit,
        'tarball_sha256': sha256(tarball),
        'license': 'MIT',
    }
    return commit


GFW_HOST = re.compile(r'^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z][a-z0-9-]*[a-z0-9]$')


def gfwlist_domains(text):
    """Extract the domains an AutoProxy list proxies.

    Keeps the host of every blocking rule and drops what cannot be expressed as
    a plain domain: exceptions (@@), regular expressions, wildcards, IP
    addresses and comments.
    """
    domains = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(('!', '[', '@@', '/')):
            continue
        rule = line.lstrip('|')
        rule = re.sub(r'^[a-z]+://', '', rule)
        rule = rule.lstrip('.')
        host = re.split(r'[/:?^]', rule, maxsplit=1)[0].lower()
        if '*' in host or not GFW_HOST.match(host):
            continue
        try:
            ipaddress.ip_address(host)
            continue
        except ValueError:
            pass
        domains.add(host)
    # A domain already covered by a parent domain adds nothing.
    kept = sorted(d for d in domains
                  if not any(d.endswith('.' + p) for p in _parents(d) if p in domains))
    return kept


def _parents(domain):
    labels = domain.split('.')
    return ['.'.join(labels[i:]) for i in range(1, len(labels) - 1)]


def update_gfwlist(lock):
    commit = head_commit(GFWLIST_REPO, 'master')
    log(f'gfwlist {commit}')
    encoded = raw(GFWLIST_REPO, commit, 'gfwlist.txt')
    text = base64.b64decode(b''.join(encoded.split())).decode('utf-8')
    domains = gfwlist_domains(text)
    target = os.path.join(GEOSITE_DIR, 'gfw')
    if os.path.exists(target):
        raise SystemExit(f'{DLC_REPO} now has its own "gfw" list; decide which one to keep')
    with open(target, 'w', encoding='utf-8', newline='\n') as fp:
        fp.write('# Generated from https://github.com/gfwlist/gfwlist '
                 f'({commit}) by scripts/update-sources.py. LGPL-2.1.\n')
        fp.write(''.join(d + '\n' for d in domains))
    with open(os.path.join(LICENSES_DIR, 'LGPL-2.1-gfwlist.txt'), 'wb') as fp:
        fp.write(raw(GFWLIST_REPO, commit, 'COPYING.txt'))
    log(f'  {len(domains)} domains')
    lock['gfwlist'] = {
        'repository': f'https://github.com/{GFWLIST_REPO}',
        'commit': commit,
        'gfwlist_txt_sha256': sha256(encoded),
        'license': 'LGPL-2.1',
    }


# --- geoip -------------------------------------------------------------------

def dbip_month():
    if os.environ.get('DBIP_MONTH'):
        return [os.environ['DBIP_MONTH']]
    today = datetime.datetime.now(datetime.timezone.utc).date().replace(day=1)
    previous = (today - datetime.timedelta(days=1)).replace(day=1)
    # A month's release appears a day or two into the month.
    return [today.strftime('%Y-%m'), previous.strftime('%Y-%m')]


def fetch_dbip(kind):
    for month in dbip_month():
        url = f'https://download.db-ip.com/free/dbip-{kind}-lite-{month}.csv.gz'
        try:
            data = fetch(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log(f'  {url}: not published')
                continue
            raise
        log(f'dbip-{kind}-lite {month}')
        return month, url, data
    raise SystemExit(f'no DB-IP {kind} release found')


def update_geoip(lock):
    shutil.rmtree(GEOIP_DIR, ignore_errors=True)
    os.makedirs(GEOIP_DIR)
    lists = {}

    # Countries: DB-IP IP to Country Lite, CC BY 4.0.
    month, url, data = fetch_dbip('country')
    lock['dbip-country-lite'] = {
        'url': url, 'release': month, 'sha256': sha256(data), 'license': 'CC-BY-4.0',
    }
    with gzip.open(io.BytesIO(data), 'rt', encoding='utf-8', newline='') as fp:
        for first, last, cc in csv.reader(fp):
            cc = cc.lower()
            # ZZ marks reserved and unallocated space; "private" covers it.
            if not re.fullmatch(r'[a-z]{2}', cc) or cc == 'zz':
                continue
            lists.setdefault(cc, []).extend(range_to_networks(first, last))

    # Mainland China: the ranges Chinese operators announce over BGP, which
    # tracks what actually routes inside the mainland more closely than a
    # registration or geolocation database. Replaces DB-IP's "cn".
    commit = head_commit(CHINA_IP_REPO, CHINA_IP_BRANCH)
    log(f'china-operator-ip {commit}')
    cn = []
    files = {}
    for name in ('china.txt', 'china6.txt'):
        body = raw(CHINA_IP_REPO, commit, name)
        files[name + '_sha256'] = sha256(body)
        cn.extend(parse_networks(body.decode('utf-8')))
    if len(cn) < 1000:
        raise SystemExit(f'china-operator-ip returned only {len(cn)} ranges')
    lists['cn'] = cn
    with open(os.path.join(LICENSES_DIR, 'MIT-china-operator-ip.txt'), 'wb') as fp:
        fp.write(raw(CHINA_IP_REPO, commit, 'LICENSE'))
    lock['china-operator-ip'] = {
        'repository': f'https://github.com/{CHINA_IP_REPO}',
        'branch': CHINA_IP_BRANCH, 'commit': commit, 'license': 'MIT', **files,
    }

    # Services: the ranges each operator publishes, plus what its ASNs
    # announce according to DB-IP IP to ASN Lite, CC BY 4.0.
    with open(os.path.join(ROOT, 'config', 'asn.json'), encoding='utf-8') as fp:
        asn_lists = {k: v for k, v in json.load(fp).items() if not k.startswith('_')}
    wanted = {int(a[2:]): name for name, asns in asn_lists.items() for a in asns}
    month, url, data = fetch_dbip('asn')
    lock['dbip-asn-lite'] = {
        'url': url, 'release': month, 'sha256': sha256(data), 'license': 'CC-BY-4.0',
    }
    services = {name: [] for name in list(asn_lists) + list(PUBLISHED_RANGES)}
    with gzip.open(io.BytesIO(data), 'rt', encoding='utf-8', newline='') as fp:
        for row in csv.reader(fp):
            name = wanted.get(int(row[2]))
            if name:
                services[name].extend(range_to_networks(row[0], row[1]))

    published = []
    for name, sources in PUBLISHED_RANGES.items():
        for kind, src in sources:
            body = fetch(src)
            published.append({'list': name, 'url': src, 'sha256': sha256(body)})
            services[name].extend(parse_published(kind, body))
    lock['published-ranges'] = published

    for name, networks in services.items():
        if name in lists:
            raise SystemExit(f'service list {name!r} clashes with a country code')
        if not networks:
            raise SystemExit(f'no ranges for {name!r}')
        lists[name] = networks

    for name in sorted(lists):
        write_list(os.path.join(GEOIP_DIR, name + '.txt'), lists[name])
    log(f'  {len(lists)} geoip lists')


def parse_published(kind, body):
    if kind == 'text':
        return parse_networks(body.decode('utf-8'))
    doc = json.loads(body)
    if kind == 'google-json':
        return [ipaddress.ip_network(p.get('ipv4Prefix') or p['ipv6Prefix'])
                for p in doc['prefixes']]
    if kind == 'fastly-json':
        return [ipaddress.ip_network(p) for p in doc['addresses'] + doc['ipv6_addresses']]
    if kind == 'aws-cloudfront-json':
        return ([ipaddress.ip_network(p['ip_prefix'])
                 for p in doc['prefixes'] if p['service'] == 'CLOUDFRONT']
                + [ipaddress.ip_network(p['ipv6_prefix'])
                   for p in doc['ipv6_prefixes'] if p['service'] == 'CLOUDFRONT'])
    raise ValueError(kind)


def main():
    os.makedirs(LICENSES_DIR, exist_ok=True)
    # No timestamp: an unchanged upstream must leave the lock file unchanged,
    # so a scheduled run with nothing new produces no diff.
    lock = {}
    dlc_commit = update_dlc(lock)
    update_gfwlist(lock)
    update_geoip(lock)
    with open(LOCK_FILE, 'w', encoding='utf-8', newline='\n') as fp:
        json.dump(lock, fp, indent=2, sort_keys=True)
        fp.write('\n')
    # The update workflow pins the geosite generator to this same commit.
    print(dlc_commit)


if __name__ == '__main__':
    main()
