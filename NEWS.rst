=============================
NEWS for system-image updater
=============================

2.1 (2014-02-18)
================
 * Internal improvements to SignatureError for better debugging. (LP: #1279056)
 * Better protection against several possible race conditions during
   `CheckForUpdate()` (LP: #1277589)
   - Use a threading.Lock instance as the internal "checking for update"
     barrier instead of a boolean.  This should eliminate the race window
     between testing and acquiring the checking lock.
   - Put an exclusive claim on the `com.canonical.SystemImage` system dbus
     name, and if we cannot get that claim, exit with an error code 2.  This
     prevents multiple instances of the D-Bus system service from running at
     the same time.
 * Return the empty string from `ApplyUpdate()` D-Bus method.  This restores
   the original API (patch merged from Ubuntu package, given by Didier
   Roche).  (LP: #1260768)
 * Request ubuntu-download-manager to download all files to temporary
   destinations, then atomically rename them into place.  This avoids
   clobbering by multiple processes and mimics changes coming in u-d-m.
 * Provide much more detailed logging.
   - `Mediator` instances have a helpful `repr` which also includes the id of
     the `State` object.
   - More logging during state transitions.
   - All emitted D-Bus signals are also logged (at debug level).
 * Added `-L` flag to nose test runner, which can be used to specify an
   explicit log file path for debugging.
 * Don't initialize the root logger, since this can interfere with
   python-dbus, which doesn't initialize its loggers correctly.

2.0.5 (2014-01-30)
==================
 * MANIFEST.in: Make sure the .bzr directory doesn't end up in the
   sdist tarball.

2.0.4 (2014-01-30)
==================
 * No change release to test the new landing process.

2.0.3 (2013-12-11)
==================
 * More attempted DEP-8 test failure fixes.

2.0.2 (2013-12-03)
==================
 * Fix additional build environment test failures.  (LP: #1256947)

2.0.1 (2013-11-27)
==================
 * Fix some build environment test failures.

2.0 (2013-11-13)
================
 * Avoid re-downloading data files if previously download files are found and
   are still valid (by checksum and gpg signature).  (LP: #1217098)
 * In the D-Bus API, `ApplyUpdate()` is changed from a synchronous method
   returning a string to an asynchronous method not returning anything.
   Instead a `Rebooting(bool)` signal is added with the value being the status
   if the reboot operation (obviously, this signal isn't ever received if the
   reboot succeeds).  (LP: #1247215)
 * Remove the old channels.json format. (LP: #1221843)
 * Remove support for old version numbers. (LP: #1220238)
 * Switch to nose2 as the test runner.  (LP: #1238071)
   + Add -P option to provide much nicer test pattern matching.
   + Add -V option to increase `systemimage` logging verbosity during tests
     (separate from nose2's own -v options).
 * Write the `ubuntu_command` file atomically.  (LP: #1241236)
 * Remove the unused `-u` and `--upgrade` switches.
 * Clarify that `--channel` should be used with `--build 0` to switch
   channels. (LP: #1243612)
 * `--info` output will include the alias name if the current channel.ini has
   a `channel_target` variable.
 * `--dry-run` output now includes channel switch information when an upgrade
   changes the channel alias mapping.
 * Add a workaround for LP: #1245597, caused by a bug in
   ubuntu-download-manager when presented with an empty download list.
 * If an existing image-master or image-signing key is found on the file
   system, double check its signature (LP: #1195057) and expiration date (LP:
   #1192717) if it has one, before using it.
 * If the winning path includes two URLs which map to the same local
   destination file name, the download should fail.  (LP: #1250181)
 * Provide a bit more useful traceback in various places of the state machine
   so that error conditions in system-image-cli make a bit more sense.
   (LP: #1248639)
 * Tweak the scoring algorithm to highly discourage candidate upgrade paths
   that don't leave you at the maximum build number.  (LP: #1250553)
 * When running system-image-cli under verbosity 1, print dots to stderr so
   that the user knows something is happening.
 * Remove unused `state_file` setting from client.ini.

1.9.1 (2013-10-15)
==================
 * Further refinement of permission checking/fixing.  (LP: #1240105)
 * Work around some failures in DEP 8 tests.  (LP: #1240106)

1.9 (2013-10-14)
================
 * Fix file and directory permissions.  A random temporary directory inside
   /tmp (by default, see `[system]tempdir` in client.ini) is securely created
   for actual ephemeral files.  The log file will have 0600 permission.
   (LP: #1235975)
 * Download files directly to the cache partition or data partition.
   (LP: #1233521)
 * Proactively remove files from the cache and data partitions before starting
   to download anything (except `log` and `last_log` in the cache partition).
   This avoid various problems that can occur if the reboot fails (LP:
   #1238102) and improves the ability to recover from partial downloads
   without rebooting (LP: #1233521).
 * Keep the D-Bus process alive as long as progress is being made (as tracked
   by any calls, internally or externally to D-Bus methods or signals).
   (LP: #1238290)
 * Pause/resume downloads. (LP: #1237360)
 * Remove all references to the `[system]threads` variable since it is no
   longer used, after the integration of the download manager.
 * Through the use of the psutil library, re-enable some previously skipped
   tests.  (LP: #1206588)

1.8 (2013-10-02)
================
 * Support channel alias tracking.  If the channel.ini file has a
   `channel_target` key, and the channel spec in the channel.json file has an
   `alias` key, and these don't match, then the channel alias has changed, and
   we squash the build number to 0 for upgrade path calculation.  An explicit
   `--build` option for system-image-cli still overrides this.  (LP: #1221844)
 * Support *phased updates* where we can ignore some images if their
   'phased-percentage' key is less than a machine-specific value.
   (LP: #1231628)
 * Switch the default `auto_download` value back to '1', i.e. download
   automatically but only over wifi.  (LP: #1229807)
 * Plumb progress signals from ubuntu-download-manager through the
   system-image D-Bus API.  (LP: #1204618)
 * Only send the `UpdateFailed` signal in response to a `CancelUpdate()` call
   if a download is already in progress.  No signal is sent if there's no
   download in progress.  Getting the files to determine whether an update is
   available or not does not count as a "download in progress". (LP: #1215946)

1.7 (2013-09-30)
================
 * Fix test suite failure on 32 bit systems.  Again.
 * Reset the D-Bus reactor timeout every time we see an active signal from the
   D-Bus service we're talking to.  (LP: #1233379)

1.6 (2013-09-30)
================
 * Use the new ubuntu-download-manager to manage all requested downloads.
   (LP: #1196991)
 * Use /userdata/.last_update file as the "last upgrade date" if the file
   exists.  (LP: #1215943)
 * Default D-Bus service timeout is now 1 hour.
 * Default D-Bus logging level is now `info`.
 * Verbose (i.e. `debug`) logging now includes the scores and paths for all
   upgrade candidates, from highest score (biggest loser) to lowest score
   (winner) last.
 * --verbose logging level is now properly propagated to the log file.

1.5.1 (2013-09-08)
==================
 * Fix test for 32 bit systems.

1.5 (2013-09-06)
================
 * `system-image-cli --dry-run -c <bad-channel>` no longer produces a
   traceback.  You get "Already up-to-date", but use `-v` for more info.
 * `system-image-cli --info` prints additional information:
    - last update time (i.e. the mtime of `/etc/system-image/channel.ini`
      falling back to the mtime of `/etc/ubuntu-build`).
    - version details for ubuntu, the device, and any custom version, if the
      `/etc/system-image/channel.ini` file contains these details.
 * D-Bus API changes:
   - `UpdateAvailableStatus` field `last_update_date` has changes its format.
      It's still ISO 8601, but with a space instead of a 'T' separating the
      date from the time.
   - New `Info()` method returns data similar to `system-image-cli --info`.
     (LP: #1215959)
 * Support the new channels.json file format with backward compatibility (for
   now) with the old format.  (LP: #1221841)

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
