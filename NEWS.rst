=============================
NEWS for system-image updater
=============================

1.0 (2013-XX-XX)
================

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
