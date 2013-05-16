To do
=====

 - logging/debugging
 - reading files from the file system (e.g. current version)
   - build version
 - partial candidates, e.g. not enough disk space to get from where we are to
   where we want to be, so multiple download/reboots necessary
 - suspend/resume
   - partial downloads (keep size, concat & check)
 - any kind of notification
   - callbacks for progress
 - issue reboots
   - dropping the download files into whatever paths the reboot needs (but
     right now I'm thinking that the cli will write a JSON output file naming
     the download location).
   - ordering of zip files
   - pluggable since reboots may be different per device
 - how do we change channels?  store the current channel along with the
   current version so we know that if we change channels, we need a new full
   one bundle image, multiple downloads (indep/dep)
   - need to download latest full to change channels
   - command line switch
   - not supported by partials
 - switch to developer (a.k.a. apt-get) mode
   - grab tarball from server to initialize apt updates
   - if dpkg exists we're in developer mode
 - query parameters in urls but only used for smart servers
 - downloads in the background / throttling
 - wifi only upgrades
 - dbus api
 - put current build version in User-Agent
 - full testing through lxc containers


Hand off
========
 - Store command into /cache/recovery/command
   --update_package=path  - OTA package file
   --wipe_data - erase user data and reboot
 - adb reboot recovery
 - http://blog.surgut.co.uk/2013/02/flash-nexus7-like-rock-star.html
 - https://wiki.ubuntu.com/ImageBasedUpgrades/Mobile/GPG
