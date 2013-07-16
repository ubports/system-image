==========
client.ini
==========


-----------------------------------------------
Ubuntu System Image Upgrader configuration file
-----------------------------------------------

:Author: Barry Warsaw <barry@ubuntu.com>
:Date: 2013-07-12
:Copyright: 2013 Canonical Ltd.
:Version: 0.5
:Manual section: 5


DESCRIPTION
===========

/etc/system-image/client.ini is the configuration file for the system image
upgrader.  It is an ini-style configuration file with sections that define the
service to connect to, as well as local system resources.  Generally, the
options never need to be changed.


SYNTAX
======

Sections are delimited by square brackets, e.g. ``[service]``.  Variables
inside the service separate the variable name and value by a colon.  Blank
lines and lines that start with a ``#`` are ignored.


THE SERVICE SECTION
===================

The section that starts with ``[service]`` defines the remote host name and
ports that provide upgrade images.  Because some files are downloaded over
HTTP and others over HTTPS, both ports must be defined.  This section contains
the following variables:

base
    The host name to connect to containing the upgrade.  This host must
    provide both HTTP and HTTPS services.

http_port
    The port for HTTP connections.

https_port
    The port for HTTPS connections.

threads
    The number of parallel download threads that can be spawned.  This allows
    multiple files to be downloaded in parallel.

timeout
    The maximum allowed time interval for downloading the individual files.
    The actual time to complete the downloading of all required files may be
    longer than this timeout.  This variable takes a numeric value followed by
    an optional interval marker.  Supported markers are ``w`` for weeks, ``d``
    for days, ``h`` for hours, ``m`` for minutes, and ``s`` for seconds.  When
    no marker is given, the default is seconds.  Thus a value of ``1m``
    indicates a timeout of one minute, while a value of ``15`` indicates a
    timeout of 15 seconds.  A negative or zero value indicates that there is
    no timeout.


THE SYSTEM SECTION
==================

The section that starts with ``[system]`` defines attributes of the local
system to be upgraded.  Every system has an upgrade *channel* and a *device*
name.  The channel roughly indicates the frequency with which the server will
provide upgrades.  The channel and device combine to define a URL path on the
server to look for upgrades appropriate to the given device on the given
schedule.  The specification for these paths is given in `[1]`_.

This section contains the following variables:

channel
    The upgrade channel.

device
    This system's device type.

build_file
    The file on the local file system containing the system's current build
    number.

tempdir
    A directory on the local file system that can be used to store temporary
    files.


THE GPG SECTION
===============

The section that starts with ``[gpg]`` defines paths on the local file system
used to cache GPG keyrings in compressed tar format.  The specification for
the contents of these files is given in `[2]`_.  This section contains the
following variables:

archive_master
    The location on the local file system for the archive master keyring.
    This key will never expire and never changes.

image_master
    The location on the local file system for the image master keyring.  This
    key will never expire and will change only rarely, if ever.

image_signing
    The location on the local file system for the image signing keyring.  This
    key expires after two years, and is updated regularly.

device_signing
    The location on the local file system for the optional device signing
    keyring.  If present, this key expires after one month and is updated
    regularly.


THE UPDATER SECTION
===================

This section defines directories where upgrade files will be placed for
recovery reboot to apply.  This section contains the following variables:

cache_partition
    The directory bind-mounted read-write from the Android side into the
    Ubuntu side, containing the bulk of the upgrade files.

data_partition
    The directory bind-mounted read-only from the Ubuntu side into the Android
    side, generally containing only the temporary GPG blacklist, if present.


THE HOOKS SECTION
=================

This section provides minimal capability to customize the upgrader operation
by selecting different upgrade path winner scoring algorithms and different
reboot commands.  This section contains the following variables:

scorer
    The Python import path to the class implementing the upgrade scoring
    algorithm.

reboot
    The Python import path to the class that implements the system reboot
    command.


SEE ALSO
========

system-image-cli(1)

[1]: https://wiki.ubuntu.com/ImageBasedUpgrades/Server

[2]: https://wiki.ubuntu.com/ImageBasedUpgrades/GPG

.. _[1]: https://wiki.ubuntu.com/ImageBasedUpgrades/Server
.. _[2]: https://wiki.ubuntu.com/ImageBasedUpgrades/GPG
