================
system-image.ini
================


------------------------------------------------
Ubuntu System Image Upgrader configuration files
------------------------------------------------

:Author: Barry Warsaw <barry@ubuntu.com>
:Date: 2015-01-15
:Copyright: 2013-2015 Canonical Ltd.
:Version: 3.0
:Manual section: 5


DESCRIPTION
===========

``/etc/system-image/config.d`` is the default configuration directory for the
system image upgrader.  It contains ini-style configuration files with
sections that define the service to connect to, as well as local system
resources.  Generally, the options never need to be changed.

The system image upgrader will read all files in this directory that start
with a numeric prefix, followed by an underscore, and then any alphanumeric
suffix, ending in ``.ini``.  E.g. ``07_myconfig.ini``.

The files are read in sorted numerical order, from lowest prefix number to
highest, with later configuration files able to override any variable in any
section.


SYNTAX
======

Sections in the ``.ini`` files are delimited by square brackets,
e.g. ``[service]``.  Variables inside the service separate the variable name
and value by a colon.  Blank lines and lines that start with a ``#`` are
ignored.


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
    The port for HTTP connections.  This is an integer, or the string
    ``disabled`` if you wish to disable all HTTP connections and use only
    HTTPS.  It is an error to disable both the HTTP and HTTPS services.

https_port
    The port for HTTPS connections.  This is an integer, or the string
    ``disabled`` if you wish to disable all HTTPS connections and use only
    HTTP.  It is an error to disable both the HTTP and HTTPS services.

channel
    The upgrade channel.

device
    The device name.  If missing or unset (i.e. the empty string), then the
    device is calculated using the ``[hooks]device`` callback.

build_number
    The system's current build number.


THE SYSTEM SECTION
==================

The section that starts with ``[system]`` defines attributes of the local
system to be upgraded.  Every system has an upgrade *channel* and a *device*
name.  The channel roughly indicates the frequency with which the server will
provide upgrades.  The system is queried for the device.  The channel and
device combine to define a URL path on the server to look for upgrades
appropriate to the given device on the given schedule.  The specification for
these paths is given in `[1]`_.

This section contains the following variables:

tempdir
    The base temporary directory on the local file system.  When any of the
    system-image processes run, a secure subdirectory inside `tempdir` will be
    created for the duration of the process.

logfile
    The file where logging output will be sent.

loglevel
    The level at which logging information will be emitted.  There are two
    loggers which both log messages to `logfile`.  "systemimage" is the main
    logger, but additional logging can go to the "systemimage.dbus" logger.
    The latter is used in debugging situations to get more information about
    the D-Bus service.

    `loglevel` can be a single case-insensitive string corresponding to the
    following `log levels`_ from least verbose to most verbose: ``DEBUG``,
    ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``.  In this case, the
    "systemimage" logger will be placed at this level, while the
    "systemimage.dbus" logger will be placed at the ``ERROR`` level.

    `loglevel` can also describe two levels, separated by a colon.  In this
    case, the main logger is placed at the first level, while the D-Bus logger
    is placed at the second level.  For example: ``debug:info``.

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

The section that starts with ``[updater]`` defines directories where upgrade
files will be placed for recovery reboot to apply.  This section contains the
following variables:

cache_partition
    The directory bind-mounted read-write from the Android side into the
    Ubuntu side, containing the bulk of the upgrade files.

data_partition
    The directory bind-mounted read-only from the Ubuntu side into the Android
    side, generally containing only the temporary GPG blacklist, if present.


THE HOOKS SECTION
=================

The section that starts with ``[hooks]`` provides minimal capability to
customize the upgrader operation by selecting different upgrade path winner
scoring algorithms and different reboot commands.  This section contains the
following variables:

device
    The Python import path to the class implementing the device query
    command.

scorer
    The Python import path to the class implementing the upgrade scoring
    algorithm.

apply
    The Python import path to the class that implements the mechanism for
    applying the update.  This often reboots the device.

    *New in system-image 3.0: ``reboot`` was renamed to ``apply``*


THE DBUS SECTION
================

The section that starts with ``[dbus]`` controls operation of the
``system-image-dbus(8)`` program.  This section contains the following
variables:

lifetime
    The total lifetime of the DBus server.  After this amount of time, it will
    automatically exit.  The format is the same as the ``[system]timeout``
    variable.


SEE ALSO
========

system-image-cli(1)


[1]: https://wiki.ubuntu.com/ImageBasedUpgrades/Server

[2]: https://wiki.ubuntu.com/ImageBasedUpgrades/GPG

.. _[1]: https://wiki.ubuntu.com/ImageBasedUpgrades/Server
.. _[2]: https://wiki.ubuntu.com/ImageBasedUpgrades/GPG
.. _`log levels`: http://docs.python.org/3/howto/logging.html#when-to-use-logging
