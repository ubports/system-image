#!/usr/bin/python3

import os

tmpdir = os.environ['ADTTMP']
artifacts = os.environ['ADT_ARTIFACTS']

os.makedirs(os.path.join(tmpdir, 'android'), exist_ok=True)
os.makedirs(os.path.join(tmpdir, 'ubuntu'), exist_ok=True)

substitutions = dict(
    TMPDIR=tmpdir,
    ARTIFACTS=artifacts,
    )

with open('debian/tests/client.ini.in', encoding='utf-8') as fp:
    ini_template = fp.read()

ini_contents = ini_template.format(**substitutions)

with open(os.path.join(tmpdir, 'client.ini'), 'w', encoding='utf-8') as fp:
    fp.write(ini_contents)
