#!/usr/bin/env python3
"""Check that the built .dat files contain every category config/required.txt
names, each with at least one entry.

Xray refuses to start when a routing rule names a category missing from its
.dat file, so a missing list would break the app rather than just a rule.

Reads the files directly: geoip.dat and geosite.dat are a protobuf list
(field 1) of entries, each with a name (field 1) and its CIDRs or domains
(field 2). Usage: check-dat.py <dir with the .dat files>
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def varint(buf, pos):
    result = shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7


def fields(buf):
    """Yield (field number, wire type, value) for one protobuf message."""
    pos = 0
    while pos < len(buf):
        key, pos = varint(buf, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = varint(buf, pos)
        elif wire == 1:
            value, pos = buf[pos:pos + 8], pos + 8
        elif wire == 2:
            length, pos = varint(buf, pos)
            value, pos = buf[pos:pos + length], pos + length
        elif wire == 5:
            value, pos = buf[pos:pos + 4], pos + 4
        else:
            raise ValueError(f'unsupported wire type {wire}')
        yield number, wire, value


def categories(path):
    """Map each category name (lower case) to its number of entries."""
    with open(path, 'rb') as fp:
        data = fp.read()
    out = {}
    for number, wire, entry in fields(data):
        if number != 1 or wire != 2:
            continue
        name, count = None, 0
        for n, w, v in fields(entry):
            if n == 1 and w == 2:
                name = v.decode('utf-8').lower()
            elif n == 2 and w == 2:
                count += 1
        if name is None:
            raise ValueError(f'{path}: entry without a name')
        out[name] = count
    return out


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'out')
    required = []
    with open(os.path.join(ROOT, 'config', 'required.txt'), encoding='utf-8') as fp:
        for line in fp:
            line = line.split('#', 1)[0].split()
            if line:
                required.append((line[0], line[1]))

    found = {}
    failures = []
    for dat, name in required:
        if dat not in found:
            found[dat] = categories(os.path.join(outdir, dat))
            print(f'{dat}: {len(found[dat])} categories')
        count = found[dat].get(name, 0)
        status = 'ok' if count else 'MISSING'
        print(f'  {status:7} {dat} {name} ({count} entries)')
        if not count:
            failures.append(f'{dat}:{name}')
    if failures:
        sys.exit('missing or empty: ' + ', '.join(failures))


if __name__ == '__main__':
    main()
