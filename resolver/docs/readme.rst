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




.. _`full specification`: https://wiki.ubuntu.com/ImageBasedUpgrades/Mobile
.. _`more detail`: https://wiki.ubuntu.com/ImageBasedUpgrades/Mobile#Full_vs._partial_updates
