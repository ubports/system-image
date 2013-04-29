To do
=====

 - logging
 - async i/o for downloading files
 - reading files from the file system (e.g. current version)
 - partial candidates, e.g. not enough disk space to get from where we are to
   where we want to be, so multiple download/reboots necessary
 - any kind of notification
 - other kinds of policies
 - dropping the download files into whatever paths the reboot needs (but right
   now I'm thinking that the cli will write a JSON output file naming the
   download location).

Change
======
 - instead of android/ubuntu-rootfs use device dependent/independent
   add a “reboot” flag in the json for the image
   - if you see a reboot flag, stop downloading after that image and issue a
     reboot could cause multiple reboots
   - if no reboot flag seen in entire path, it has to be the same as a full
     update add support for query parameters in url, but only for smart server.
     probably ignored for dumb server
 - device indep/dep version strings
 - locale + country code  xx_YY
 - device static information - config file
 - description of update
   - description-xx_YY for localized version
   - fallback to description-xx
   - fallback to description
 - always issue reboot at end of downloads, even if no reboot flag found,
   otherwise updates won’t be applied
 - suspend/resume
 - callbacks for progress
 - partial downloads (keep size, concat & check)
 - prioritize deltas over fulls (specified in ini file)
 - separate signatures on image files
 - how do we change channels?  store the current channel along with the
   current version so we know that if we change channels, we need a new full
   one bundle image, multiple downloads (indep/dep)

