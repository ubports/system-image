================
system-image-cli
================

------------------------------------------------
Ubuntu System Image Upgrader command line script
------------------------------------------------

:Author: Barry Warsaw <barry@ubuntu.com>
:Date: 2015-01-15
:Copyright: 2013-2015 Canonical Ltd.
:Version: 3.0
:Manual section: 1


SYNOPSIS
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

-b NUMBER, --build NUMBER
    Override the device's current build number just this once.  ``NUMBER``
    must be an integer.  Use ``-b 0`` for force an upgrade.

-c CHANNEL, --channel CHANNEL
    Override the device's upgrade channel just this once.  Use in combination
    with ``--build 0`` to switch channels.

--switch CHANNEL
    This is a convenience alias for the combination of ``-b 0 -c CHANNEL``.
    It is an easier way to switch channels.  If ``-switch`` is given with
    ``-b`` and/or ``-c``, the latter take precedence.

--list-channels
    Lists the available channels, including aliases, and exits.

-d DEVICE, --device DEVICE
    Override the device name just this once.

--f FILTER, --filter FILTER
    Filter the candidate upgrade paths to only contain full or delta updates.
    ``FILTER`` must be either ``full`` or ``delta``.

-i, --info
    Show some information about the current device, including the current
    build number, device name, and channel, then exit.

-n, --dry-run
    Calculate and print the upgrade path, but do not download or apply it.
    *New in system-image 2.5.1: output displays the target phase percentage*

-p VALUE, --percentage VALUE
    For testing purposes, force a device specific phase percentage.  The value
    must be an integer between 0 and 100.  *New in system-image 2.5.1*

-g, --no-apply
    Downloads all files and prepares for, but does not actually apply the
    update.  On devices which require a reboot to apply the update, no reboot
    is performed.  *New in system-image 3.0: --no-reboot is renamed to
    --no-apply*

-v, --verbose
    Increase the logging verbosity.  With one ``-v``, logging goes to the
    console in addition to the log file, and logging at ``INFO`` level is
    enabled.  With two ``-v`` (or ``-vv``), logging both to the console and to
    the log file are output at ``DEBUG`` level.

-C DIR, --config DIR
    Use the given configuration directory, otherwise use the system default.
    The program will read all the files in this directory that begin with a
    number, followed by an underscore, and ending in ``.ini``
    (e.g. ``03_myconfig.ini``).  The files are read in sorted numerical order
    from lowest prefix number to highest, with later configuration files able
    to override any variable in any section.

--factory-reset
    Wipes the data partition and issues a reboot into recovery.  This
    effectively performs a device factory reset.

--show-settings
    Show all the key/value pairs in the settings database.

--get KEY
    Print the value for the given key in the settings database.  If the key is
    missing, a default value is printed.  May be given multiple times.

--set KEY=VALUE
    Set the value for the given key in the settings database.  If the key is
    missing it is added.  May be given multiple times.

--del KEY
    Deletes the given key from the settings database.  If the key does not
    exist, this is a no-op.  May be given multiple times.


FILES
=====

/etc/system-image/[0-9]+*.ini
    Default configuration files.


SEE ALSO
========

system-image.ini(5), system-image-dbus(8)
