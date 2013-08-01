# This Source Code is subject to the terms of the Mozilla Public License
# version 2.0 (the "License"). You can obtain a copy of the License at
# http://mozilla.org/MPL/2.0/.

# Advanced Programming in the UNIX(r) Environment, Second Edition
# W. Richard Stevens, Stephen A. Rago
# 13.2 Daemon Processes - Coding Rules
# Figure 13.1
#
# http://code.activestate.com/recipes/278731/
# Chad J. Schroeder

import os
import resource
import sys

class Daemon(object):
    def __init__(self, options):
        if not options.daemonize:
            return

        # Fork once and exit parent so child is not a process group leader
        # which is requried to create a new session.
        if os.fork():
            exit(0)

        # Create a new session.
        os.setsid()

        # Fork again to make sure child is not a session leader.
        # Use _exit in order to not call clean up handlers in the child.
        if os.fork():
            os._exit(0)

        # Change working directory to root so that we don't prevent any file
        # systems from being unmounted during a reboot.
        os.chdir('/')

        # Do not inherit parent's umask.
        os.umask(0)

        # Close any open file descriptors inherited from the parent.
        try:
            soft_maxfd, hard_maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)
        except:
            soft_maxfd, hard_maxfd = (1024, 1024)

        for fd in range(0, soft_maxfd):
            try:
                os.close(fd)
            except OSError:
                pass

        # open /dev/null as stdin (fd 0) for read/write.
        fd0 = open("/dev/null", "r+")
        assert fd0.fileno() == 0, "expected file descriptor 0"
        # Duplicate stdin (fd 0) to stdout (fd 1), stderr (fd 2).
        os.dup2(0, 1)
        os.dup2(0, 2)

        self.pidfile = options.pidfile
        pidfile = open(self.pidfile, "w")
        pidfile.write('%i' % os.getpid())
        pidfile.close()

def main():
    from optparse import OptionParser

    parser = OptionParser()

    parser.add_option("--pidfile",
                      action="store",
                      type="string",
                      dest="pidfile",
                      default="%s/daemonize.pid" % os.getcwd(),
                      help="Path to pidfile. "
                      "Defaults to daemonize.pid in current directory.")

    parser.add_option("--daemonize",
                      action="store_true",
                      type=boolean,
                      default=False,
                      help="Runs in daemon mode.")

    (options, args) = parser.parse_args()
    daemon = Daemon(options)

if __name__ == "__main__":
    main()
