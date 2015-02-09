=================
system-image-dbus
=================

-----------------------------------------
Ubuntu System Image Upgrader DBus service
-----------------------------------------

:Author: Barry Warsaw <barry@ubuntu.com>
:Date: 2015-01-15
:Copyright: 2013-2015 Canonical Ltd.
:Version: 3.0
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

-C DIR, --config DIR
    Use the given configuration directory, otherwise use the system default.
    The program will read all the files in this directory that begin with a
    number, followed by an underscore, and ending in ``.ini``
    (e.g. ``03_myconfig.ini``).  The files are read in sorted numerical order
    from lowest prefix number to highest, with later configuration files able
    to override any variable in any section.


D-BUS API
=========

This process exports a D-Bus API on the bus name ``com.canonical.SystemImage``,
object path ``/Service``, and interface ``com.canonical.SystemImage``.  The
D-Bus service process is normally started by D-Bus activation.

The API specification follows.  In all cases, where strings are described,
they are UTF-8 encoded, and in English where appropriate.  All datetimes are
encoded as UTF-8 strings in the UTC timezone using the *combined* format
(i.e. 'T' separating the date and time portions), with 1 second resolution.

The calls may be synchronous or asynchronous.  In the former case, the return
values are described.  In the latter case, a description of the possible
signals a client may receive is given; see the detailed description of the
signals for details of their payload.


Methods
-------

``CheckForUpdate()``
    This is an **asynchronous** call instructing the client to check whether
    an update is available.  If a check is already in progress, it continues.
    If the client is in *auto-download* mode (see below), then this call will
    automatically begin to download the update if one is available, otherwise
    the download must be explicitly initiated by a ``DownloadUpdate()`` call.
    It is possible for an update to only occur if certain criteria are met,
    e.g. only if the devices is on wifi.  ``CheckForUpdate()`` never resumes a
    paused download.  In all cases, an ``UpdateAvailableStatus`` signal is
    emitted containing the results of the check.  If the device is in
    auto-download mode, an ``UpdateProgress`` signal is sent as soon as the
    download is started.

``DownloadUpdate()``
    This is an **asynchronous** call used to begin the downloading of an
    available update, and it is a no-op if there is no update to download, a
    download is already in progress, ``CheckForUpdate()`` was not called
    first, or the update status is in an error condition.  If a previous
    download was paused, ``DownloadUpdate()`` resumes the download.  An
    ``UpdateProgress()`` signal is sent as soon as the download begins.  Other
    status signals as described below will be sent when the download
    terminates.

``ApplyUpdate()``
    This is an **asynchronous** call used to apply a previously downloaded
    update.  After the update has been applied, an ``Applied`` signal is
    sent.  Some devices require a reboot in order to apply the update, and
    such devices may also issue a ``Rebooting`` signal.  However, on devices
    which require a reboot, the timing and emission of both the ``Applied``
    and ``Rebooting`` signals are in a race condition with system shutdown,
    and may not occur.

``CancelUpdate()``
    This is a **synchronous** call to cancel any update check or download in
    progress.  The empty string is returned unless an error occurred, in which
    case the error message is returned.

``PauseDownload()``
    This is a **synchronous** method to pause the current download.  The empty
    string is returned unless an error occurred, in which case the error
    message is returned.

``Info()``
    **Deprecated** (see ``Information()``).  This is a **synchronous** call
    which returns some information about the current state of the device.  The
    following pieces of information are returned, as a tuple:

    * *current build number* - the current build number as an integer.
    * *device name* - the name of the device type.
    * *channel name* - the channel the device is currently on.
    * *last update date* - the last time this device was updated as a
      datetime, e.g. "YYYY-MM-DDTHH:MM:SS"
    * *version detail* - a mapping of strings to strings, where the keys are
      component names and the values are the version numbers for that
      component.

``Information()``
    This is a **synchronous** call which returns an extensible mapping of
    UTF-8 keys to UTF-8 values.  The following keys are currently defined:

    * *current_build_number* - The current build number as an integer.
    * *target_build_number* - If an update is known to be available, this will
      be the build number that an update will leave the device at.  If no
      `CheckForUpdate()` has been previously performed, then the
      *target_build_number* will be "-1".  If a previous check has been
      performed, but no update is available (i.e., the device is already at
      the latest version), then *target_build_number* will be the same as
      *current_build_number*.
    * *device_name* - The name of the device type.
    * *channel_name* - The channel the device is currently on.
    * *last_update_date* - The last time this device was updated as a
      datetime, e.g. "YYYY-MM-DDTHH:MM:SS"
    * *version_detail* - A string containing a comma-separated list of
      key-value pairs providing additional component version details,
      e.g. "ubuntu=123,mako=456,custom=789".
    * *target_version_detail* - Like *version_detail* but contains the
      information from the server.  If an update is known to be available,
      this will be taken from ``index.json`` file's image specification, for
      the image that the upgrade will leave the device at.  If no update is
      available this will be identical to *version_detail*.  If no
      `CheckForUpdate()` as been previously performed, then the
      *target_version_detail* will be the empty string.
    * *last_check_date* - The last time a ``CheckForUpdate()`` call was
      performed.

    *New in system-image 2.3*

    *New in system-image 2.5: target_build_number was added.*

    *New in system-image 3.0: target_version_detail was added.*

``FactoryReset()``
    This is a **synchronous** call which wipes the data partition and issue a
    reboot to recovery.  A ``Rebooting`` signal may be sent, depending on
    timing.

    *New in system-image 2.3*.

``ProductionReset()``
    This is a **synchronous** call which wipes the data partition, sets a flag
    for factory wipe (used in production), and issue a reboot to recovery.
    A ``Rebooting`` signal may be sent, depending on timing.

    *New in system-image 3.0*.

``SetSetting(key, value)``
    This is a **synchronous** call to write or update a setting.  ``key`` and
    ``value`` are strings.  While any key/value pair may be set, some keys
    have predefined semantics and values.  See below for details.

    If the new value is different than the old value, or if the key was not
    previously set, a ``SettingChanged`` signal is sent.

    For values with the above semantics, any invalid value is ignored
    (i.e. *not* set or stored).

    Keys with underscore prefixes are reserved for user defined values.

``GetSetting(key)``
    This is a **synchronous** call to read and return a setting.  If ``key``
    has not been previously set, the empty string is returned.  Note that
    some of the pre-defined keys have default settings.

``Exit()``
    This is a **synchronous** call which causes the D-Bus service process to
    exit immediately.  There is no return value.  If ``Exit()`` is never
    called, the service will still exit normally after some configurable
    amount of time.  D-Bus activation will restart it.


Signals
-------

``UpdateAvailableStatus(is_available, downloading, available_version, update_size, last_update_date, error_reason)``
    Sent in response to a ``CheckForUpdate()`` call, this signal provides
    information about the state of the update.  The signal includes these
    pieces of information:

    * **is_available** - A boolean flag which indicates whether an update is
      available or not.  This will be false if the device's build number is
      equal to or greater than any candidate build on the server (IOW, there
      is no candidate available).  This flag will be true when there is an
      update available.
    * **downloading** - A boolean flag indicating whether a download is in
      progress.  This doesn't include any preliminary downloads needed to
      determine whether a candidate is available or not (e.g. keyrings,
      blacklists, channels.json, and index.json files).  This flag will be
      false if a download is paused.
    * **available_version** - A string specifying the update target candidate
      version.
    * **update_size** - An integer providing total size in bytes for an
      available upgrade.  This does not include any preliminary files needed
      to determine whether an update is available or not.
    * **last_update_date** - The ISO 8601 format UTC date (to the second) that
      the last update was applied to this device.  This will be the empty
      string if no update has been previously applied.
    * **error_reason** - A string indicating why the download did not
      start.  Only useful if the second argument (downloading) is false,
      otherwise ignore this value.

    Depending on the state of the system, some of the arguments of this signal
    may be ignored.  Some example signal values include:

    * ``UpdateAvailableStatus(true, true, build_number, size,
      "YYYY-MM-DDTHH:MM:SS", descriptions, "")`` - This means that an update
      is available and is currently downloading. The build number of the
      candidate update is given, as is its total size in bytes, and the
      descriptions of the updates in all available languages.
    * ``UpdateAvailableStatus(true, false, build_number, size,
      "YYYY-MM-DDTHH:MM:SS", descriptions, "paused")`` - This means that an
      update is available, but it is not yet downloading, possibly because the
      client is in manual-update mode, or because the download is currently
      paused.  The reason is given in the last argument, and the build number,
      size, and descriptions are given as above.
    * ``UpdateAvailableStatus(false, ?, ?, ?, "YYYY-MM-DDTHH:MM:SS", ?, ?)`` -
      There is no update available. The ISO 8601 date of the last applied
      update is given, but all other arguments should be ignored.

``UpdateProgress(percentage, eta)``
    Sent periodically, while a download is in progress.  This signal is not
    sent when an upgrade is paused.

    * **percentage** - An integer between 0 and 100 indicating how much of the
      download (not including preliminary files) have been currently
      downloaded.  This may be 0 if we do not yet know what percentage has
      been downloaded.
    * **eta** - The estimated time remaining to complete the download, in
      float seconds. This may be 0 if we don't have a reasonable estimate.

``UpdatePaused(percentage)``
    Sent whenever a download is paused as detected via the download service.

    * **percentage** - An integer between 0 and 100 indicating how much of the
      download (not including preliminary files) have been currently
      downloaded.  May be 0 if this information cannot be obtained.

``UpdateDownloaded()``
    Sent when the currently in progress update has been completely and
    successfully downloaded.  When this signal is received, it means that the
    device is ready to have the update applied via ``ApplyUpdate()``.

``UpdateFailed(consecutive_failure_count, last_reason)``
    Sent when the update failed for any reason (including cancellation, but
    only if a download is in progress).  The client will remain in the failure
    state until the next ``CheckForUpdate()`` call.

    * **consecutive_failure_count** - An integer specifying the number of
      times in a row that a ``CheckForUpdate()`` has resulted in an update
      failure.  This increments until an update completes successfully
      (i.e. until the next ``UpdateDownloaded`` signal is issued).
    * **last_reason** - A string containing the reason for why this updated
      failed.

``Applied(status)``
    Sent in response to an ``ApplyUpdate()`` call.  See the timing caveats for
    that method.  **New in system-image 3.0**

    * **status** - A boolean indicating whether an update has been applied or
      not.

``Rebooting(status)``
    On devices which require a reboot in order to apply an update, this signal
    may be sent in response to an ``ApplyUpdate()`` call.  See the timing
    caveats for that method.

    * **status** - A boolean indicating whether the device has initiated a
      reboot sequence or not.

``SettingChanged(key, value)``
    Sent when a setting is changed.  This signal is not sent if the new value
    is the same as the old value.  Both the key and value are strings.

    * **key** - The key of the value that was changed.
    * **value** - The new value for the key.


Additional API details
----------------------

The ``SetSetting()`` call takes a key string and a value string.  The
following keys are predefined.

    * *min_battery* - The minimum battery strength which will allow downloads
      to proceed.  The value is the string representation of a number between
      0 and 100 percent.
    * *auto_download* - A tri-state value indicating whether downloads should
      normally proceed automatically if an update is available when a
      ``CheckForUpdate()`` was issued.  The value is the string representation
      of the following integer values:

      * *0* - Never download automatically; i.e. an explicit
        ``DownloadUpdate()`` call is required to start the download.
      * *1* - Only download automatically if the device is connected via wifi.
        *This is the default*.
      * *2* - Always download the update automatically.

    * *failures_before_warning* - Unused by the client, but stored here for
      use by the user interface.



FILES
=====

/etc/system-image/[0-9]+*.ini
    Default configuration files.

/etc/dbus-1/system.d/com.canonical.SystemImage.conf
    DBus service permissions file.

/usr/share/dbus-1/system-services/com.canonical.SystemImage.service
    DBus service definition file.


SEE ALSO
========

system-image.ini(5), system-image-cli(1)


.. _`ISO 8601`: http://en.wikipedia.org/wiki/ISO_8601
