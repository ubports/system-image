To do
=====

 - logging
 - debugging
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
 - base url should not include http/https
   - infer this from the file type and the spec
 - separate signatures on image files
 - how do we change channels?  store the current channel along with the
   current version so we know that if we change channels, we need a new full
   one bundle image, multiple downloads (indep/dep)
 - switch to developer (a.k.a. apt-get) mode
   - grab tarball from server to initialize apt updates
   - if dpkg exists we're in developer mode
 - query parameters in urls but only used for smart servers
 - downloads in the background / throttling
 - wifi only upgrades
 - dbus api
 - put current build version in User-Agent
 - Don't cache channels.json, it's not worth it
 - Combine the cache and config objects... if we keep the cache at all
