# This Source Code is subject to the terms of the Mozilla Public License
# version 2.0 (the "License"). You can obtain a copy of the License at
# http://mozilla.org/MPL/2.0/.

import os, sys, re
import optparse
import subprocess
import httplib
import json
import requests

LINK_SPEEDS = ['Cable', 'DSL', 'DSL', 'Dial', 'Fios', 'Native']

class WptOptions(optparse.OptionParser):
    def __init__(self, **kwargs):
        optparse.OptionParser.__init__(self, **kwargs)
        defaults = {}

        self.add_option("--revision",
                        action="store", dest="revision",
                        help="revision of the try server build that you wish to run")
        defaults["revision"]=None

        self.add_option("--host",
                        action="store", dest="host",
                        help="hostname of the wpt-controller (default: localhost)")
        defaults["host"] = 'localhost'

        self.add_option("--port",
                        action="store", dest="port",
                        help="port that the wpt-controller is running on (default: 80)")
        defaults["port"] = '80'

        self.add_option("--username",
                        action="store", dest="username",
                        help="username used to push to try")
        defaults["username"]=None

        self.add_option("--build",
                        action="store", dest="build",
                        help="full url to the build to test (currently only supported is a people.mozilla.org account)")
        defaults["build"]=None

        self.add_option("--link_speed",
                        action="append", dest="linkSpeed",
                        help="define the link speed to run the test: %s" % ','.join(LINK_SPEEDS))
        defaults["linkSpeed"]=[]

        self.add_option("--urls",
                        action="append", dest="urls",
                        help="url, list of urls, or filename of urls to run tests on")
        defaults["urls"]=[]

        self.set_defaults(**defaults)
        usage = """
                  pushwpt.py ssh://hg.mozilla.org/try  <- will find username in ~/.hgrc and get revision from hg push
                  pushwpt.py ssh://username@mozilla.com@hg.moizlla.org/try <- will find rev from push stdout
                  pushwpt.py ssh://hg.mozilla.org/try --link_speed 3g,dsl --urls www.bbc.co.uk,www.wordpress.com
                """

    def verifyOptions(self, options):
        if options.build:
            if options.revision or options.username:
                print "ERROR: if you are specifying a specific build, you cannot specify a revision and username"
                sys.exit(1)

            # http://people.mozilla.org/~jmaher/firefox-24.win32.exe
            # verify people account
            if not options.build.startswith('http://people.mozilla.org/~'):
                print "ERROR: please specify a build that starts with 'http://people.mozilla.org/~'"
                sys.exit(1)

            # verify build exists
            server = 'http://people.mozilla.org'
            path = options.build.split(server)[-1]
            conn = httplib.HTTPConnection(server)
            conn.request('HEAD', path)
            response = conn.getresponse()
            conn.close()
            if response.status != 200:
                print "ERROR: unable to verify '%s' exists" % options.build
                sys.exit(1)

        if options.revision:
            if not re.match('([0-9a-fA-F]{12})', options.revision):
                print "ERROR: invalid revision '%s', it must be 12 hexidecimal characters" % options.revision
                sys.exit(1)

        if options.username:
            if not re.match('[^@ ]+@[^@ ]+\.[^@ ]+', options.username):
                print "ERROR: invalid email address '%s', please specify a valid email address as the username" % options.username
                sys.exit(1)

        if options.linkSpeed:
            ls = []
            for opt in options.linkSpeed:
                ls.extend(opt.split(','))
            for opt in ls:
                if opt not in LINK_SPEEDS:
                    print "ERROR: invalid link speed '%s', please use the valid options: %s" % (options.linkSpeed, ','.join(LINK_SPEEDS))
                    sys.exit(1)
            options.linkSpeed = ls

        #TODO: do we want this as a default?
        if not options.linkSpeed:
            options.linkSpeed = ['native']

        if options.urls:
            ls = []
            for opt in options.urls:
                ls.extend(opt.split(','))
            options.urls = ls

        #TODO: do we want this as a default?
        if not options.urls:
            options.urls = ['www.mozilla.org']

        return options

def getHgrcData(options):
    if options.username:
        return options

    with open(os.path.join(os.getenv("HOME"), '.hgrc'), 'r') as hgrc:
        data = hgrc.read()

    for line in data.split('\n'):
        if line.startswith('username'):
            fullname = line.split('=')[1].strip()
            parts = fullname.split('<')
            if len(parts) > 1:
                options.username = parts[1].split(">")[0]

    return options

def getHgLog(options):
    if options.revision:
        return options

    proc = subprocess.Popen(['hg', 'log', '-l', '1'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout = proc.communicate()[0]
    for line in stdout.split('\n'):
        if line.startswith('changeset:'):
            options.revision = line.split(':')[-1]

    return options

def postToWPTQueue(options):
    host = '%s:%s' % (options.host, options.port)
    options =  {'urls': options.urls, 'speeds': options.linkSpeed, 'email': options.username, 'build': options.build}
    controller = 'http://%s/wpt-controller/accept-jobs.wsgi' % host
    print "controller: %s" % controller
    print "options: %s" % options
    r = requests.post(controller, data=json.dumps(options))
    print r
    return

def main():
    parser=WptOptions()
    options, args=parser.parse_args()

#    if len(args) != 1:
#        print "ERROR: please specify the branch to push to (i.e. 'ssh://hg.mozilla.org/try')"
#        sys.exit(1)

    options = parser.verifyOptions(options)
    if not options.build:
        options = getHgrcData(options)
        options = getHgLog(options)
        options.build = 'http://ftp.mozilla.org/pub/mozilla.org/firefox/try-builds/%s-%s/try-win32/' % (options.username, options.revision)

    if len(args) == 1:
        parts = args[0].split('/')
        if parts[-1] != 'try':
            print "ERROR: please push to try server, not %s" % parts[-1]
            sys.exit(1)

        if len(args[0].split('@')) > 1:
            namerepo = parts[-2].split('@')
            options.username = '@'.join(namerepo[0:-1])
    postToWPTQueue(options)


if __name__ == "__main__":
    main()
