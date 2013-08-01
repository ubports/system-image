================
system-image-cli
================

------------------------------------------------
Ubuntu System Image Upgrader command line script
------------------------------------------------

:Author: Barry Warsaw <barry@ubuntu.com>
:Date: 2013-07-31
:Copyright: 2013 Canonical Ltd.
:Version: 1.0
:Manual section: 1


SYNOPSYS
========

system-image-cli [options]


DESCRIPTION
===========

This script upgrades the system to the latest available image (i.e. build
number).  With no options, this script checks the latest version available on
the server and calculates an upgrade path to that version from the system's
current version.  If an upgrade path is found, the relevant files are
downloaded and the upgrade is applied by rebooting the system into recovery
mode.


OPTIONS
=======

-h, --help
    Show the program's message and exit.

--version
    Show the program's version number and exit.

-b, --build
    Show the system's current build number and exit.

-v, --verbose
    Increase the logging verbosity.  With one ``-v``, logging goes to the
    console in addition to the log file, and logging at ``INFO`` level is
    enabled.  With two ``-v`` (or ``-vv``), logging both to the console and to
    the log file are output at ``DEBUG`` level.

-C FILE, --config FILE
    Use the given configuration file, otherwise use the default.

-u NUMBER, --upgrade NUMBER
    Calculate an upgrade path from the given build number instead of the
    system's actual build number.

--dbus
    Run in D-Bus client mode.  Normally, ``system-image-cli`` runs directly
    against the internal API.  With this switch, it instead acts as a D-Bus
    client, performing all operations against the ``system-image-dbus``
    service.  This mode more closely mimics how a user interface would perform
    updates.


FILES
=====

/etc/system-image/client.ini
    Default configuration file.


SEE ALSO
========

client.ini(5), system-image-dbus(8)
