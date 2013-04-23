=====================
Resolution of updates
=====================

This package implements a prototype resolver for determining how to update a
device to the latest image.  The `full specification`_ is available online.

This package doesn't actually perform the updates, but it has several tools
that serve as core pieces to the update story.  In summary:

 * A site publishes a summary of the images that are available.
 * This tool downloads a description of what's available
 * This tool inspects the current device to determine what is installed
 * A resolver is executed which compares what's available to what's installed,
   and returns a set of images that should be applied to get the device to the
   latest image
 * Different criteria can be applied to resolution order (tentative).  By
   default resolution is optimized for minimal download size
 * If not enough disk space is available, the resolver may spit out a partial
   update, i.e. getting the device closer, but requiring subsequent
   resolutions to complete the update
 * If no resolution is possible either because the device is in a funny state
   (e.g. too old, or apt-get'ted to an unknown state), or because of a lack of
   available disk space, an error is returned
 * The output of the resolver is JSON file containing the results

Another tool reads this JSON file, performs the downloads, putting the files
in the proper location and causing a reboot to perform the update.  These
tasks are out of scope for this tool.


Full vs. partial updates
========================

As describe in `more detail`_ full and partial images are available.  E.g. for
the last 3 months of release:

==========  =====================   ==================================
Release id  Description             We release
==========  =====================   ==================================
201303-0    First month release     full image
201303-1    security update         full image and delta from 201303-0
201303-1    security update         full image and delta from 201303-0
201303-2    security update         full image and delta from 201303-0
                                    and delta from 201303-1
201304-0    April monthly release   full image and delta from 201303-2
201304-1    security update         full image and delta from 201304-0
201304-2    security update         full image and delta from 201304-0
                                    and delta from 201304-1
201304-3    security update         full image and delta from 201304-0
                                    and delta from 201304-2
201304-4    security update         full image and delta from 201304-0
                                    and delta from 201304-3
201304-5    security update         full image and delta from 201304-0
                                    and delta from 201304-4
201305-0    May monthly release     full image and delta from 201304-5
==========  =====================   ==================================


Devices should never be more than one full and one delta from the latest
version, but it might be necessary, or the system may elect, to update from a
series of deltas, e.g. due to size considerations.


Builds and images
=================

There are two types of builds and associated images automated monthly images,
and manually triggered urgent security and/or bug fix releases.

Monthly images contain:
 * A new full disk image
 * A partial disk image from the last full image

Update images contain:
 * A new full disk image
 * A partial disk image from the last full monthly image
 * A partial disk image from the last update image after the last monthly

Images are numbered YYYYMMXX where YYYY is the year, MM is the month and XX
is the build number.


Discovery
=========

First, the system needs to know about the available channels, and which
channel it's interested in.  This will usually be the *stable* channel,
although some users will want the more bleeding edge *daily* channel.  Other
channels may also be available.

At the top of the server hierarchy are three files, and directories for each
available channel.  The files are:

 * ``phablet.pubkey.asc`` - This is the public key used to sign various other
   files in the hierarchy.  In order to prevent man-in-the-middle attacks, the
   system must download this key over https.
 * ``channels.json`` - This file contains a listing of all the available
   channels.  It's contents are detailed below.
 * ``channels.json.asc`` - The detached signature of the ``channels.json``
   file.


Channels
--------

The ``channels.json`` contains a listing of all available channels as keys in
the top-level mapping.  Each channel listing further has a mapping naming the
available devices.  Each device name is mapped to the path, rooted at the top
of the hierarchy which names the *index* file, in JSON format.  This index
file contains all the details for the updates which are available for that
device, in that channel.

The channel files are not expected to change very often, so they can be
cached.  If a channel/device is requested that is unknown, the top-level
channels listing can be reacquired.  Occasionally, on a schedule TBD, the
cached channels listing can be refreshed.


Configuration
-------------

There is a configuration file for the resolver which is used to define static
information about the upgrade process.  This includes the base URL for
contacting the update server, local file system cache directories, cache entry
lifetimes, and the channel and device type for this system's upgrades.  As an
example::

    # Configuration file for specifying relatively static information about the
    # upgrade resolution process.
    [service]
    base: https://phablet.stgraber.org

    [cache]
    directory: /var/cache/resolver
    lifetime: 14d

    [upgrade]
    channel: stable
    device: nexus7

The device with the above configuration file will upgrade to the stable Nexus
7 image.



.. _`full specification`: https://wiki.ubuntu.com/ImageBasedUpgrades/Mobile
.. _`more detail`: https://wiki.ubuntu.com/ImageBasedUpgrades/Mobile#Full_vs._partial_updates
