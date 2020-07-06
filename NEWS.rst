=============================
NEWS for system-image updater
=============================

3.3 (2020-07-06)
================
  * Return only channels which can be installed on the current device for
    com.canonical.SystemImage GetChannels
  * No longer test for Python 3.4

3.1 (2016-03-02)
================
 * In ``system-image-cli``, add a ``-m``/``--maximage`` flag which can be used
   to cap a winning upgrade path to a maximum image number.  (LP: #1386302)
 * Remove the previously deprecated ``Info()`` D-Bus method.  (LP: #1380678)
 * Remove the previously deprecated ``--no-reboot`` command line option.
 * Add support for temporarily overriding the wifi-only setting when using
   ubuntu-download-manager.  (LP: #1508081)
   - Added ``ForceAllowGSMDownload()`` method to the D-Bus API.
   - Added ``DownloadStarted`` D-Bus signal, which gets sent when the download
     for an update has begun.
   - Added ``--override-gsm`` flag to ``system-image-cli``.

3.0.2 (2015-09-22)
==================
 * Don't crash when one of the .ini files is a dangling symlink.
   (LP: #1495688)

3.0.1 (2015-06-16)
==================
 * When `--progress=json` is used, print an error record to stdout if the
   state machine fails.  (LP: #1463061)

3.0 (2015-05-08)
================
 * Support a built-in PyCURL-based downloader in addition to the traditional
   ubuntu-download-manager (over D-BUS) downloader.  Auto-detects which
   downloader to use based on whether udm is available on the system bus,
   pycurl is importable, and the setting of the SYSTEMIMAGE_PYCURL environment
   variable.  Initial contribution by Michael Vogt.  (LP: #1374459)
 * Support alternative machine-id files as fall backs if the D-Bus file does
   not exist.  Specifically, add systemd's /etc/machine-id to the list.
   Initial contribution by Michael Vogt.  (LP: #1384859)
 * Support multiple configuration files, as in a `config.d` directory.  Now,
   configuration files are named `NN_whatever.ini` where "NN" must be a
   numeric prefix.  Files are loaded in sorted numeric order, with later files
   overriding newer files.  Support for both the `client.ini` and
   `channel.ini` files has been removed. (LP: #1373467)
 * The `[system]build_file` variable has been removed.  Build number
   information now must come from the `.ini` files, and last update date
   comes from the newest `.ini` file loaded.
 * The `-C` command line option now takes a path to the configuration
   directory.
 * Reworked the checking and downloading locks/flags to so that they will work
   better with configuration reloading.  (LP: #1412698)
 * Support for the `/etc/ubuntu-build` file has been removed.  The build
   number now comes from the configuration files.  (LP: #1377312)
 * Move the `archive-master.tar.xz` file to `/usr/share/system-image` for
   better FHS compliance.  (LP: #1377184)
 * Since devices do not always reboot to apply changes, the `[hooks]update`
   variable has been renamed to `[hooks]apply`.  (LP: #1381538)
 * For testing purposes only, `system-image-cli` now supports an
   undocumented command line switch `--skip-gpg-verification`.  Originally
   given by Jani Monoses.  (LP: #1333414)
 * A new D-Bus signal `Applied(bool)` is added, which is returned in
   response to the `ApplyUpdate()` asynchronous method call.  For devices
   which do not need to reboot in order to apply the update, this is the only
   signal you will get.  If your device needs to reboot you will also receive
   the `Rebooting(bool)` command as with earlier versions.  The semantics of
   the flag argument are the same in both cases, as are the race timing issues
   inherent in these signals.  See the `system-image-dbus(8)` manpage for
   details.  (LP: #1417176)
 * As part of LP: #1417176, the `--no-reboot` switch for
   `system-image-cli(1)` has been deprecated.  Use `--no-apply` instead
   (`-g` is still the shortcut).
 * Support production factory resets.  `system-image-cli --production-reset`
   and a new D-Bus API method `ProductionReset()` are added.  Given by Ricardo
   Salveti.  (LP: #1419027)
 * A new key, `target_version_detail` has been added to the dictionary
   returned by the `.Information()` D-Bus method.  (LP: #1399687)
 * The `User-Agent` HTTP header now also includes device and channel names.
   (LP: #1387719)
 * Added `--progress` flag to `system-image-cli` for specifying methods for
   reporting progress.  Current available values are: `dots` (compatible with
   system-image 2.5), `logfile` (compatible with system-image 2.5's
   `--verbose` flag), and `json` for JSON records on stdout.  (LP: #1423622)
 * Support for the `SYSTEMIMAGE_DBUS_DAEMON_HUP_SLEEP_SECONDS` environment
   variable has been removed.
 * Fix `system-image-cli --list-channels`.  (LP: #1448153)

2.5.1 (2014-10-21)
==================
 * Make phased upgrade percentage calculation idempotent for each tuple of
   (channel, target-build-number, machine-id).  Also, modify the candidate
   upgrade path selection process such that if the lowest scored candidate
   path has a phased percentage greater than the device's percentage, the
   candidate will be ignored, and the next lowest scored candidate will be
   checked until either a winner is found or no candidates are left, in which
   case the device is deemed to be up-to-date. (LP: #1383539)
 * `system-image-cli -p/--percentage` is added to allow command line override
   of the device's phased percentage.
 * `system-image-cli --dry-run` now also displays the phase percentage of the
   winning candidate upgrade path.

2.5 (2014-09-29)
================
 * Remove the previously deprecated `system-image-cli --dbus` command line
   switch.  (LP: #1369717)
 * Add a `target_build_number` key to the mapping returned by the
   `.Information()` D-Bus method.  (LP: #1370586)

2.4 (2014-09-16)
================
 * The channel.ini file can override the device name by setting
   ``[service]device``.  (LP: #1353178)
 * Add optional instrumentation to collect code coverage data during test
   suite run via tox.  (LP: #1324241)
 * When an exception occurs in a `system-image-dbus` D-Bus method, signal, or
   callback, this exception is logged in the standard log file, and the
   process exits.  Also, `[system]loglevel` can now take an optional ":level"
   prefix which can be used to set the log level for the D-Bus API methods.
   By default, they log at `ERROR` level, but can be set lower for debugging
   purposes.  (LP: #1279970)
 * Don't crash when releasing an unacquired checking lock.  (LP: #1365646)
 * When checking files for `last_update_date()` ignore PermissionErrors and
   just keep checking the fall backs.  (LP: #1365761)
 * `system-image-cli --dbus` has been deprecated and will be removed in the
   future.  (LP: #1369714)

2.3.2 (2014-07-31)
==================
 * When system-image-{cli,dbus} is run as non-root, use a fallback location
   for the settings.db file, if the parent directory isn't writable.
   (LP: #1349478)

2.3.1 (2014-07-23)
==================
 * Fix a traceback that occurs when the `systemimage.testing` subpackage isn't
   available, as is the case when the system-image-dev binary package is not
   installed.

2.3 (2014-07-16)
================
 * Support factory resets.  `system-image-cli --factory-reset` and a new D-Bus
   API method `FactoryReset()` are added.  (LP: #1207860)
 * Data file checksums are passed to ubuntu-download-manager where available.
   (LP: #1262256)
 * Certain duplicate destinations are allowed, if they have matching source
   urls and checksums.  (LP: #1286542)
 * When system-image-{cli,dbus} is run as non-root, use a fallback location
   for the log file if the system log file isn't writable.  (LP: #1301995)
 * `system-image-cli --list-channels` lists all the available channels,
   including aliases.  (LP: #1251291)
 * `system-image-cli --no-reboot` downloads all files and prepares for
   recovery, but does not actually issue a reboot.  (LP: #1279028)
  * `system-image-cli --switch <channel>` is a convenient alias for
    `system-image-cli -b 0 -c <channel>`.  (LP: #1249347)
 * Added `--show-settings`, `--get`, `--set`, and `--del` options for viewing,
   changing, and setting all the internal database settings.  (LP: #1294273)
 * Improve memory usage when verifying file checksums.  Given by Michael
   Vogt.  (LP: #1271684)
 * In the `UpdatePaused` signal, return a percentage value that's closer to
   reality than hardcoding it to 0.  (LP: #1274131)
 * New D-Bus API method `.Information()` which is like `.Info()` except that
   it returns extended information details, as a mapping of strings to
   strings.  These details include a `last_check_date` which is the ISO 8601
   timestamp of the last time an `UpdateAvailableStatus` signal was sent.
   (LP: #1280169)
 * Set the GSM flag in ubuntu-download-manager based on the current s-i
   download setting.  (LP: #1339157)
 * The system-image-dbus(8) manpage now describes the full D-Bus API.  (LP:
   #1340882)
 * Fix the D-Bus mock service so that the downloading flag for
   `UpdateAvailableStatus` will correctly return true when checking twice
   under manual downloads.  (LP: #1273354)
 * Pay down some tech-debt.  (LP: #1342183)

2.2 (2014-03-05)
================
 * When `CheckForUpdate()` is called a second time, while an auto-download is
   in progress, but after the first check is complete, we send an
   `UpdateAvailableStatus` signal with the cached information.  (LP: #1284217)
 * Close a race condition when manually downloading and issuing multiple
   `CheckForUpdate` calls.  (LP: #1287919)
 * Support disabling either the HTTP or HTTPS services for update (but not
   both).  The ``[service]http_port`` or ``[service]https_port`` may be set to
   the string ``disabled`` and the disabled protocol will fall back to the
   enabled protocol.  Implementation given by Vojtech Bocek.  (LP: #1278589)
 * Allow the channel.ini file to override the ``[service]`` section.
 * Now that ubuntu-download-manager performs atomic renames of temporary
   files, system-image no longer needs to do that.  (LP: #1287287)
 * When an exception in the state machine occurs while checking for updates,
   the exception is caught and logged.  When using the CLI, the result is an
   exit code of 1.  When using the D-Bus API, an `UpdateAvailableStatus`
   signal is sent with `error_reason` set to the exception string.  This
   exception is *not* propagated back to GLib.  (LP: #1250817)
 * Log directory path is passed to ubuntu-download-manager to assist in
   debugging.  Given by Manuel de la Peña.  (LP: #1279532)

2.1 (2014-02-20)
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
 * Fixed D-Bus error logging.
   - Don't initialize the root logger, since this can interfere with
     python-dbus, which doesn't initialize its loggers correctly.
   - Only use `.format()` based interpolation for `systemimage` logs.
 * Give virtualized buildds a fighting chance against D-Bus by
   - using `org.freedesktop.DBus`s `ReloadConfig()` interface instead of
     SIGHUP.
   - add a configurable sleep call after the `ReloadConfig()`.  This defaults
     to 0 since de-virtualized and local builds do not need them.  Set the
     environment variable `SYSTEMIMAGE_DBUS_DAEMON_HUP_SLEEP_SECONDS` to
     override.
  * Run the tox test suite for both Python 3.3 and 3.4.

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
