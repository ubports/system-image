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
   system must download this key over https.  Eventually, this key will be
   installed in the initial device flash and not typically downloaded over the
   internet.
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


Indexes
-------

The channel/device index file is where all the available images for that
combination is described.  Only the images defined in this file are available
for download for this device in this channel.

The index file has three sections: *bundles*, *global*, and *images*.  The
*global* section currently contains just a UTC date string marking when the
index file was generated, and the client updater doesn't really care about
this value.

The *images* section is a sequence describing every image file that is
available for download.  There are two types of images, *full* and *delta*.  A
full image is exactly as you'd expect, it contains the entire root filesystem
(for the Ubuntu side) or Android image needed to bring the device up to the
stated version.  Full image items contain the following keys:

 * checksum - The SHA1 hash of the zip file
 * content - Either *android* or *ubuntu-rootfs* describing whether the image
   is for the Ubuntu or Android side
 * path - The URL to the zip file, relative to the server root
 * size - The size of the zip file in bytes
 * type - Whether the image is a *full* update or *delta* from some previous
   image
 * version - A version string, which is **not** guaranteed to be a number, but
   generally will be in the YYYYMMXX format

In addition, *delta* images also have this key:

 * base - A version string in YYYYMMXX format naming the version from which
   this delta was generated

The *bundles* section is a sequence of all supported image combinations for
both the Ubuntu and Android sides.  Each bundle item contains the following
keys:

 * images - This should have both an *android* and an *ubuntu-rootfs* key, the
   values of which are version numbers for the supported bundle of images
 * version - A version string, guaranteed to be in the format YYYYMMXX where
   XX starts at 00 and is sortable.


Updates
-------

These then are the steps to determine whether the device needs to be updated:

 * Download the ``index.json`` file for the channel/device and verify it
 * Sort the available *bundles* by version, taking the highest value as the
   latest bundle.  The bundle versions are ignored after this.
 * Inspect the latest bundle to get the image versions for *ubuntu-rootfs* and
   *android*.
 * If the device's current *android* version matches the latest bundle's
   *android* version, there's nothing to do on the Android side
 * If the device's current *ubuntu-rootfs* version matches the latest bundle's
   *ubuntu-rootfs* version, there's nothing to do on the Ubuntu side
 * If either side's current image version is lower, the device needs updating

If the device needs to be updated, then you have to figure out what it can be
updated from.  In the best case scenario, the device should be at most one
full and one delta away from the latest.  Here are the steps to determine what
needs to be downloaded and applied.  This assumes that there's plenty of disk
space so multiple deltas are not necessary.

 * For each of *android* and *ubuntu-rootfs*, find all the deltas which
   matches the version number in the latest bundle.  There may be more than
   one, e.g. delta from the last monthly to this version, and delta from the
   last delta to this version.
 * Chase all the bases until you reach a YYYYMM00 version, which names the
   last monthly that the latest delta is based off of
 * Now you should have up to two chains of possible updates, running through
   the individual deltas, or from the latest delta to the latest monthly
 * Decide which chain you want :)

The decision of which chain to use is based on several criteria.  It could be
that we'll optimize for fewest downloads, in which case we'll take the
shortest chain.  Maybe we'll optimize for total download size, in which case
we'll add up all the image sizes and choose the chain with the smallest total
size.  There maybe be other criteria applied to the possible update chains to
consider, such as if there's not enough space for either chain to be
downloaded entirely.


.. _`full specification`: https://wiki.ubuntu.com/ImageBasedUpgrades/Mobile
.. _`more detail`: https://wiki.ubuntu.com/ImageBasedUpgrades/Mobile#Full_vs._partial_updates
