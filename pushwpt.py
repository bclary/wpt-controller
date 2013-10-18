# This Source Code is subject to the terms of the Mozilla Public License
# version 2.0 (the "License"). You can obtain a copy of the License at
# http://mozilla.org/MPL/2.0/.

import os, sys, re
import optparse
import subprocess
import httplib
import json
import requests
import ConfigParser

class WptOptions(optparse.OptionParser):
    def getConfig(self):
        if self.config:
            return True

        self.filename = ''
        if os.path.exists('settings.ini'):
            self.filename = 'settings.ini'
        elif os.path.exists('settings.ini.example'):
            self.filename = 'settings.ini.example'

        if not self.filename:
            return False

        try:
            self.config = ConfigParser.RawConfigParser()
            self.config.readfp(open(self.filename))
        except:
            self.config = None
            return False
        return True

    def __init__(self, **kwargs):
        optparse.OptionParser.__init__(self, **kwargs)
        defaults = {}
        self.config = None
        self.LINK_SPEEDS = ['Cable', 'DSL', 'Dial', 'Fios', 'Native', '3G',
                            'Broadband', 'ModernMobile', 'ClassicMobile']
        self.DEFAULT_LOCATIONS = []
        self.DEFAULT_URLS = []

        if self.getConfig():
            DEFAULT_LOCATIONS = self.config.get('defaults', 'locations').split(',')
            DEFAULT_URLS = self.config.get('defaults', 'urls').split(',')

        self.add_option("--revision",
                        action="store", dest="revision",
                        help="revision of the try server build that you wish to run")
        defaults["revision"] = None

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
        defaults["username"] = None

        self.add_option("--build",
                        action="store", dest="build",
                        help="full url to the build to test (currently only supported is a people.mozilla.org account)")
        defaults["build"] = None

        self.add_option("--link_speed",
                        action="append", dest="linkSpeed",
                        help="define the link speed to run the test: %s" % ', '.join(self.LINK_SPEEDS))
        defaults["linkSpeed"] = []

        self.add_option("--urls",
                        action="append", dest="urls",
                        help="list of urls, or filename of urls to run tests on: %s\ndefault: %s" % (', '.join(self.DEFAULT_URLS), 'www.mozilla.org'))
        defaults["urls"] = []

        self.add_option("--locations",
                        action="append", dest="locations",
                        help="list of locations: %s\ndefault: %s" % (', '.join(self.DEFAULT_LOCATIONS), 'bc-winxp01w:Firefox'))	
        defaults["locations"] = []

        self.add_option("--runs",
                        action="store", dest="runs",
                        help="Number of runs to perform, default: 1")
        defaults["runs"] = "1"

        self.add_option("--no_tcpdump",
                        action="store_true", dest="no_tcpdump",
                        help="Do not perform tcpdump, default : False")
        defaults["no_tcpdump"] = False

        self.add_option("--no_video",
                        action="store_true", dest="no_video",
                        help="Do not record video, default : False")
        defaults["no_video"] = False

        self.add_option("--datazilla",
                        action="store_true", dest="datazilla",
                        help="Submit results to datazilla, default : False")
        defaults["datazilla"] = False

        self.add_option("--label",
                        action="store", dest="label",
                        help="Label of the machine to test, default: user-test")
        defaults["label"] = "user-test"

        self.add_option("--prescript",
                        action="store", dest="prescript",
                        help="WebPagetest script to execute prior to page naviation, default: None. "
                        "Use \\t to embed tabs and \\n to embed newlines "
                        "in the script. "
                        "See https://sites.google.com/a/webpagetest.org/docs/using-webpagetest/scripting "
                        "for more information on scripting WebPagetest.")
        defaults["prescript"] = ""

        self.add_option("--postscript",
                        action="store", dest="postscript",
                        help="WebPagetest script to execute after to page naviation, default: None. "
                        "Use \\t to embed tabs and \\n to embed newlines "
                        "in the script. "
                        "See https://sites.google.com/a/webpagetest.org/docs/using-webpagetest/scripting "
                        "for more information on scripting WebPagetest.")
        defaults["postscript"] = ""

        self.set_defaults(**defaults)
        usage = """
                  pushwpt.py ssh://hg.mozilla.org/try  <- will find username in ~/.hgrc and get revision from hg push
                  pushwpt.py ssh://username@mozilla.com@hg.moizlla.org/try <- will find rev from push stdout
                  pushwpt.py ssh://hg.mozilla.org/try --link_speed Native,DSL --urls www.bbc.co.uk,www.wordpress.com
                """

    def verifyOptions(self, options):
        if options.build:
            if options.revision:
                print "ERROR: if you are specifying a specific build, you cannot specify a revision."
                sys.exit(1)

            # http://people.mozilla.org/~jmaher/firefox-24.win32.exe
            # verify people account
            if not options.build.startswith('http://people.mozilla.org/~'):
                print "ERROR: please specify a build that starts with 'http://people.mozilla.org/~'"
                sys.exit(1)

            # verify build exists
            server = 'people.mozilla.org'
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
                if opt not in self.LINK_SPEEDS:
                    print "ERROR: invalid link speed '%s', please use the valid options: %s" % (options.linkSpeed, ','.join(self.LINK_SPEEDS))
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

        if not options.locations:
            options.locations = ['bc-winxp01w:Firefox']

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
    options =  {'urls': options.urls,
                'speeds': options.linkSpeed,
                'email': [options.username],
                'build': [options.build],
                'label': [options.label],
                'prescript': [options.prescript],
                'postscript': [options.postscript],
                'runs': [options.runs],
                'tcpdump': [''] if options.no_tcpdump else ['on'],
                'video': [''] if options.no_video else ['on'],
                'datazilla': ['on'] if options.datazilla else [''],
                'locations': options.locations}

    print options
    controller = 'http://%s/wpt-controller/accept-jobs.wsgi' % host
    print requests.post(controller, data=json.dumps(options))
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
