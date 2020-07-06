======================
 System Image Updater
======================

This repository contains the client side tools for system image based
upgrades.  For more details, see: https://wiki.ubuntu.com/ImageBasedUpgrades


Testing
=======

To test locally run::

    $ tox

This will run the test suite against all supported Python 3 versions.

You can also run a subset of tests by using a regular expression pattern.
First you need to set up the local virtual environment.  Running `tox` as
above does this as a side-effect, but you can also set up (or update [1]_) the
environment without running the test suite::

    $ tox --notest -r

Once the environment is set up, you can run individual tests like so::

    $ .tox/py35-curl/bin/python -m nose2 -P <pattern>

Multiple `-P` options can be given.  The pattern matches the full test "name",
so you can use a file name (without the `.py` extension), a test class, a test
method, or various other combinations here.  E.g.::

    $ .tox/py35-curl/bin/python -m nose2 -P test_add_existing_key

Other options are available to help with debugging and verbosity.  Try this to
get full help::

    $ .tox/py35-curl/bin/python -m nose2 --help


Project Information
===================

(Old) Launchpad project page: https://launchpad.net/ubuntu-system-image


Filing Bugs
===========

File bugs at https://github.com/ubports/ubports-touch

This is preferred rather than using the Ubuntu source package, but if you do
file it against the source package, please also add the project as a bugtask.
Also, please tag the bug with the `client` tag (since the project page above
also refers to the server and other components of image based system
upgrades).


Author
======

You can contact the primary author/maintainer at

TODO


.. _[1]: Sometimes you need to update the environment, if for example you make
         a change to the entry points in main.py or service.py.
