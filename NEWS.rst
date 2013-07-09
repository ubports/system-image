=============================
NEWS for system-image updater
=============================

0.3 (2013-07-09)
================
 * Update the client.ini file to reflect the actual update service (which is
   now deployed) and the system partitioning on the actual device.
 * By default, search for client.ini in /etc/system-image/client.ini.  Also,
   create the /tmp and /var/lib directories if possible and they don't yet
   exist. (LP: #1199177)
 * Fix timeout error when downloading more files than the number of threads.
   (LP: #1199361)

0.2 (2013-06-27)
================
 * Fix distutils packaging bugs exposed by Debian packaging work.
 * Rename 'resolver' package to 'systemimage' and script to
   /usr/bin/system-image-cli (LP: #1193142)

0.1 (2013-06-27)
================
 * Initial release.
