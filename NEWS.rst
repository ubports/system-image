=============================
NEWS for system-image updater
=============================

1.5 (2013-XX-XX)
================
 * `system-image-cli --dry-run -c <bad-channel>` no longer produces a
   traceback.  You get "Already up-to-date", but use `-v` for more info.

1.4 (2013-08-30)
================
 * Update the `system-image-cli` manpage with the previously added switches.
 * Support the new version number regime, which uses sequential version
   numbers starting at 1.  (LP: #1218612)

1.3 (2013-08-29)
================
 * Fixed bug in resolving channels with dashes in their name. (LP: #1217932)
 * Add `system-image-cli --filter` option to allow for forcing full or delta
   updates.  (LP: #1208909)
 * Command line option changes for `system-image-cli`:
   - Added -i/--info to get current build number, device, and channel.
   - Re-purposed -c/--channel to allow for overriding the channel name.
   - Re-purposed -b/--build to allow for overriding the build number.
   - Added -d/--device to allow for overriding the device name.
 * State persistence is disabled for now.  (LP: #1218357)
 * LP: #1192575 supported by `system-image-cli -c <channel> --filter=full`.

1.2 (2013-08-26)
================
 * Add support for an optional /etc/system-image/channel.ini file, and shuffle
   some of the other /etc/system-image/client.ini file options.  (LP: #1214009)
 * Set "auto_download" mode to '0' by default (manual download).  This
   prevents inadvertent downloading over 3G until we integrate the download
   service.
 * Add -n/--dry-run option to system-image-cli.  (LP: #1212713)

1.1 (2013-08-23)
================
 * Use nose as the test runner.  This allows us to pre-initialize the logging
   to prevent unwanted output. (LP: #1207117)
 * Update the DBus API to the new specification. (LP: #1212781)

1.0 (2013-08-01)
================
 * Add manpage for system-image-dbus. (LP: #1206617)
 * Fix the dbus tests so they can all be run.  (LP: #1205163)
 * system-image-dbus must also create the tempdir if it doesn't yet exist,
   just like -cli does.  (LP: #1206515)
 * Fix upgrade path scoring and winner resolution when two candidate upgrade
   paths have the same score.  (LP: #1206866)
 * Make system-image-cli and system-image-dbus more amenable to being run in
   "demo" mode out of a virtualenv.
   - Update setup.py with run-time dependencies.
   - Add a tools/demo.ini sample configuration file which allows the full
     upgrade procedure to be executed (reboots are a no-op, and the device is
     fixed to 'grouper').
   - Give system-image-cli a --dbus option so that it will perform the update
     over dbus rather than against the internal API.
 * Major changes to the way logging is done.
   - The config file now has [system]logfile and [system]loglevel variables
     which control where and how logging goes under normal operation.
   - A single -v on the command line mirrors the log file output to the
     console, and sets both log levels to INFO level.  Two -v on the command
     line also mirrors the output, but sets the log levels to DEBUG.
 * Added tools/sd.py which serves as a DBus client for testing and debugging
   purposes.
 * Print the channel and device in the log file.  (LP: #1206898)
 * Added some useful tools for debugging in a live environment. (LP: 1207391)

0.9.2 (2013-07-30)
==================
 * system-image-dbus must run on the system bus instead of the session bus.
   Fix contributed by Loïc Minier.  (LP: #1206558)
 * Add systemimage/data/com.canonical.SystemImage.conf which will get
   installed into /etc/dbus-1/system.d/ for dbus permissions.  (LP: #1206523)
 * Use full path to executable in dbus service file.
 * system-image-dbus executable now resides in /usr/sbin
 * client.ini: Bump dbus timeout to 10 minutes.

0.9.1 (2013-07-26)
==================
 * Further DBus API refinements to better support U/I development.
   - Add a .Exit() method.
   - Calling .Cancel() immediately issues a Canceled signal.
   - .GetUpdate() and .Reboot() no longer issue Canceled signals, but they
     no-op if a .Cancel() has been previously called.

0.9 (2013-07-25)
================
 * Rename DBus method IsUpdateAvailable() to CheckForUpdate() and make it
   asynchronous.  Rename the UpdatePending() signal to UpdateAvailableStatus()
   and have it contain a boolean flag which indicates whether an update is
   available or not.  Make GetUpdate() actually asynchronous.  (LP: #1204976)
 * Add DBus method mocks (LP: #1204528)

0.8 (2013-07-24)
================
 * Calculate the device name by querying the system, rather than defining it
   as a key in the client.ini file.  (LP: #1204090)
 * Add -c/--channel option to system-image-cli; this prints the channel/device
   name being used.

0.7 (2013-07-22)
================
 * No reboot should be issued if there is no update available.  (LP: #1202915)
 * DBus API implemented.  (LP: #1192585)
 * system-image-cli -v displays the files being downloaded, but not their
   progress (use -vv for that).  (LP: #1202283)

0.6 (2013-07-15)
================
 * Fix Image hashes to fit in 32 bites, fixing FTBFS on i386 and for better
   compatibility with actual phone hardware. (LP: #1200981)

0.5 (2013-07-12)
================
 * Add manpages for system-image-cli and client.ini. (LP: #1195497)

0.4 (2013-07-10)
================
 * Fix reboot bug.  (LP: #1199981)
 * Fix ubuntu_command file ordering.  (LP: #1199986)
 * Ensure the /var/lib target directory for cached .tar.xz keyring files
   exists before copying them. (LP: #1199982)

0.3 (2013-07-09)
================
 * Update the client.ini file to reflect the actual update service (which is
   now deployed) and the system partitioning on the actual device.
 * By default, search for client.ini in /etc/system-image/client.ini.  Also,
   create the /tmp and /var/lib directories if possible and they don't yet
   exist. (LP: #1199177)
 * Fix timeout error when downloading more files than the number of threads.
   (LP: #1199361)
 * Preserve all descriptions in all languages from the index.json file.
 * State machine changes:
   - Allow the passing of a callback which is used in the big download call.
     This will be used to implement a cancel operation.
   - Add .run_thru() and .run_until() methods used for better step control.
   - Split the "prepare command file" and reboot steps.
 * The ubuntu_command file written to the recovery partition now supports the
   currently specified format. (LP: #1199498)

0.2 (2013-06-27)
================
 * Fix distutils packaging bugs exposed by Debian packaging work.
 * Rename 'resolver' package to 'systemimage' and script to
   /usr/bin/system-image-cli (LP: #1193142)

0.1 (2013-06-27)
================
 * Initial release.
