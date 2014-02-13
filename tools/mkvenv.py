#! /usr/bin/env python3
#
# Copyright (C) 2013-2014 Canonical Ltd.
# Author: Barry Warsaw <barry@ubuntu.com>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Set things up so both the client and server can run in a virtualenv."""

import os
import pwd
import sys


def makedirs(path):
    try:
        os.makedirs(path)
    except FileExistsError:
        pass


# I am a horrible script.
basedir = sys.argv[1]


def main():
    makedirs(os.path.join(basedir, 'etc', 'system-image'))
    makedirs(os.path.join(basedir, 'tmp', 'system-image'))
    makedirs(os.path.join(basedir, 'var', 'system-image'))
    path = os.path.join(basedir, 'etc', 'client.ini')
    with open(path, 'w', encoding='utf-8') as fp:
        print("""\
[service]
base: system-image.ubuntu.com
http_port: 80
https_port: 443
timeout: 1m

[system]
channel: daily
build_file: {basedir}/etc/ubuntu-build
tempdir: {basedir}/tmp/system-image
logfile: {basedir}/var/system-image/client.log
loglevel: error

[gpg]
archive_master: {basedir}/etc/system-image/archive-master.tar.xz
image_master: {basedir}/var/system-image/keyrings/image-master.tar.xz
image_signing: {basedir}/var/system-image/keyrings/image-signing.tar.xz
device_signing: {basedir}/var/system-image/keyrings/device-signing.tar.xz

[updater]
cache_partition: {basedir}/android
data_partition: {basedir}/ubuntu

[hooks]
device: systemimage.testing.demo.DemoDevice
scorer: systemimage.scores.WeightedScorer
reboot: systemimage.testing.demo.DemoReboot

[dbus]
lifetime: 10m
""".format(basedir=basedir), file=fp)

    path = os.path.join(basedir, 'etc', 'com.canonical.SystemImage.service')
    with open(path, 'w', encoding='utf-8') as fp:
        print("""\
[D-BUS Service]
Name=com.canonical.SystemImage
Exec={basedir}/bin/system-image-dbus -v -C {basedir}/etc/client.ini
User=root
""".format(basedir=basedir), file=fp)

    user = pwd.getpwuid(os.getuid()).pw_name
    path = os.path.join(basedir, 'etc', 'dbus-system.conf')
    with open(path, 'w', encoding='utf-8') as fp:
        print("""\
<!-- dbus system bus configuration file template for the test suite.
     Use Python's str.format() to do substitutions.
  -->

<!DOCTYPE busconfig PUBLIC
 "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">

<busconfig>
  <type>system</type>
  <listen>unix:tmpdir={basedir}/tmp</listen>

  <!-- Load our own services -->
  <servicedir>{basedir}/etc</servicedir>

  <policy user="{user}">
    <allow send_interface="*"/>
    <!-- Allow everything to be sent -->
    <allow send_destination="*"/>
    <!-- Allow everything to be received -->
    <allow eavesdrop="true"/>
    <!-- Allow anyone to own anything -->
    <allow own="*"/>
  </policy>

</busconfig>
""".format(basedir=basedir, user=user), file=fp)


main()
print('Be sure to copy archive-master.tar.xz* to '
      '{basedir}/etc/system-image'.format(basedir=basedir))
print('dbus-daemon --nofork --config-file={basedir}/etc/dbus-system.conf '
      '--print-address=1 --print-pid=1'.format(basedir=basedir))
