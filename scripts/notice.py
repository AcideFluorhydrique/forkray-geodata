#!/usr/bin/env python3
"""Write the attribution and license notices the geo data requires.

DB-IP's CC BY 4.0 licence asks for "IP Geolocation by DB-IP" wherever the data
is used, the MIT licences for their copyright notices, and LGPL-2.1 for its
text to accompany the gfw list. An app shipping the .dat files has to show all
of this, so this script renders it as an HTML section.

Usage:
  notice.py                      write out/NOTICE.html
  notice.py --append-to FILE     also insert the section into an HTML page,
                                 before </body> (e.g. the app's licences page)
"""

import html
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*path):
    with open(os.path.join(ROOT, *path), encoding='utf-8') as fp:
        return fp.read()


def commit():
    try:
        return subprocess.run(['git', '-C', ROOT, 'rev-parse', 'HEAD'], check=True,
                               capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return 'unknown'


def link(url, text=None):
    return f'<a href="{html.escape(url)}">{html.escape(text or url)}</a>'


def section():
    lock = json.loads(read('sources.lock.json'))
    dlc = lock['domain-list-community']
    gfw = lock['gfwlist']
    cn = lock['china-operator-ip']
    country = lock['dbip-country-lite']
    asn = lock['dbip-asn-lite']
    e = html.escape
    repo = 'https://github.com/AcideFluorhydrique/forkray-geodata'
    this = commit()
    published = sorted({p['url'] for p in lock['published-ranges']})

    parts = [
        '<h3>Notice for the geo data (geoip.dat, geosite.dat, '
        'geoip-only-cn-private.dat):</h3>',
        f'<p>Built by {link(repo, "forkray-geodata")} at {e(this)} from the sources '
        'below. The data was converted to the V2Ray format; for geoip, the DB-IP '
        'country list for China was replaced with the china-operator-ip ranges and '
        'the service lists combine published ranges with ASN prefixes.</p>',
        '<ul>',
        f'<li><b>IP Geolocation by {link("https://db-ip.com", "DB-IP")}</b>: '
        f'IP to Country Lite ({e(country["release"])}) and IP to ASN Lite '
        f'({e(asn["release"])}), licensed under '
        f'{link("https://creativecommons.org/licenses/by/4.0/", "CC BY 4.0")}.</li>',
        f'<li>{link(dlc["repository"], "v2fly/domain-list-community")} at '
        f'{e(dlc["commit"])}, MIT license (below).</li>',
        f'<li>{link(cn["repository"], "gaoyifan/china-operator-ip")} at '
        f'{e(cn["commit"])}, MIT license (below).</li>',
        f'<li>{link(gfw["repository"], "gfwlist/gfwlist")} at {e(gfw["commit"])}, '
        'converted to the geosite "gfw" list, GNU LGPL 2.1 (below).</li>',
        '<li>Address ranges published by their operators: '
        + ', '.join(link(u) for u in published) + '.</li>',
        '</ul>',
    ]
    for title, path in (('v2fly/domain-list-community', 'MIT-domain-list-community.txt'),
                        ('gaoyifan/china-operator-ip', 'MIT-china-operator-ip.txt'),
                        ('gfwlist/gfwlist', 'LGPL-2.1-gfwlist.txt')):
        parts.append(f'<p>{e(title)}:</p>')
        parts.append(f'<pre>{e(read("LICENSES", path).rstrip())}</pre>')
    parts.append('<br>')
    parts.append('<hr>')
    return '\n'.join(parts) + '\n'


def main():
    notice = section()
    os.makedirs(os.path.join(ROOT, 'out'), exist_ok=True)
    with open(os.path.join(ROOT, 'out', 'NOTICE.html'), 'w', encoding='utf-8',
              newline='\n') as fp:
        fp.write(notice)

    if len(sys.argv) == 3 and sys.argv[1] == '--append-to':
        target = sys.argv[2]
        with open(target, encoding='utf-8') as fp:
            page = fp.read()
        if page.count('</body>') != 1:
            sys.exit(f'{target}: expected exactly one </body>')
        if 'Notice for the geo data' in page:
            sys.exit(f'{target}: already contains the geo data notice')
        with open(target, 'w', encoding='utf-8', newline='\n') as fp:
            fp.write(page.replace('</body>', notice + '  </body>'))
    elif len(sys.argv) != 1:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
