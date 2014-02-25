=================
system-image-dbus
=================

-----------------------------------------
Ubuntu System Image Upgrader DBus service
-----------------------------------------

:Author: Barry Warsaw <barry@ubuntu.com>
:Date: 2013-07-31
:Copyright: 2013-2014 Canonical Ltd.
:Version: 1.0
:Manual section: 8


SYNOPSYS
========

system-image-dbus [options]


DESCRIPTION
===========

The DBus service published by this script upgrades the system to the latest
available image (i.e. build number).  With no options, this starts up the
``com.canonical.SystemImage`` service.


OPTIONS
=======

-h, --help
    Show the program's message and exit.

--version
    Show the program's version number and exit.

-v, --verbose
    Increase the logging verbosity.  With one ``-v``, logging goes to the
    console in addition to the log file, and logging at ``INFO`` level is
    enabled.  With two ``-v`` (or ``-vv``), logging both to the console and to
    the log file are output at ``DEBUG`` level.

-C FILE, --config FILE
    Use the given configuration file, otherwise use the default.  The program
    will optionally also read a ``channel.ini`` file in the same directory as
    ``FILE``.


FILES
=====

/etc/system-image/client.ini
    Default configuration file.

/etc/system-image/channel.ini
    Optional configuration file overrides (for the ``[service]`` section
    only).

/etc/dbus-1/system.d/com.canonical.SystemImage.conf
    DBus service permissions file.

/usr/share/dbus-1/system-services/com.canonical.SystemImage.service
    DBus service definition file.


SEE ALSO
========

client.ini(5), system-image-cli(1)
