#!/usr/bin/python3

# Copyright (C) 2013-2015 Canonical Ltd.
# Author: Barry Warsaw <barry@ubuntu.com>

import os

tmpdir = os.environ['ADTTMP']
artifacts = os.environ['ADT_ARTIFACTS']

os.makedirs(os.path.join(tmpdir, 'android'), exist_ok=True)
os.makedirs(os.path.join(tmpdir, 'ubuntu'), exist_ok=True)

config_d = os.path.join(tmpdir, 'config.d')
os.makedirs(config_d, exists_ok=True)

substitutions = dict(
    TMPDIR=tmpdir,
    ARTIFACTS=artifacts,
    )

with open('debian/tests/00_default.ini.in', encoding='utf-8') as fp:
    ini_template = fp.read()

ini_contents = ini_template.format(**substitutions)

default_ini = os.path.join(config_d, '00_default.ini')
with open(default_ini, 'w', encoding='utf-8') as fp:
    fp.write(ini_contents)
