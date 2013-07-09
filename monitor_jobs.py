#!/usr/bin/env python
# This Source Code is subject to the terms of the Mozilla Public License
# version 2.0 (the "License"). You can obtain a copy of the License at
# http://mozilla.org/MPL/2.0/.

import ConfigParser
import datetime
import httplib2
import json
import logging
import md5
import os
import random
import re
import sqlite3
import tempfile
import time
import urllib

import BeautifulSoup
# TODO(bc) Replace wpt_batch_lib
import wpt_batch_lib

from logging.handlers import TimedRotatingFileHandler
from emailhandler import SMTPHandler

class JobMonitor:
    def __init__(self, options):

        self.database = options.database

        if not os.path.exists(self.database):
            logging.error("database file %s does not exist" % self.database)
            exit(2)

        try:
            self.connection = sqlite3.connect(self.database)
            self.connection.execute("PRAGMA foreign_keys = ON;")
            self.cursor = self.connection.cursor()
        except sqlite3.OperationalError:
            logging.exception("Could not get database connection to %s" % self.database)
            exit(2)

        self.job = None

        config = ConfigParser.RawConfigParser()
        config.readfp(open(options.settings))

        self.sleep_time = config.getint('server', 'sleep_time')
        self.check_minutes = config.getint('server', 'check_minutes')
        self.server = config.get('server', 'server')
        self.api_key = config.get('server', 'api_key')
        self.firefoxpath = config.get('server', 'firefoxpath')
        self.firefoxdatpath = config.get('server', 'firefoxdatpath')

        self.mail_username = config.get('mail', 'username')
        self.mail_password = config.get('mail', 'password')
        self.mail_host = config.get('mail', 'mailhost')

        self.admin_toaddrs = config.get('admin', 'admin_toaddrs').split(',')
        self.admin_subject = config.get('admin', 'admin_subject')
        self.admin_loglevel = logging.DEBUG
        try:
            self.admin_loglevel = getattr(logging,
                                          config.get('admin',
                                                     'admin_loglevel'))
        except AttributeError:
            pass
        except ConfigParser.Error:
            pass

        # Set up the root logger to log to a daily rotated file log.
        self.logfile = options.log
        self.logger = logging.getLogger()
        self.logger.setLevel(self.admin_loglevel)
        filehandler = TimedRotatingFileHandler(self.logfile,
                                               when='D',
                                               interval=1,
                                               backupCount=7,
                                               encoding=None,
                                               delay=False,
                                               utc=False)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        filehandler.setFormatter(formatter)
        self.logger.addHandler(filehandler)

        # Set up the administrative logger with an SMPT handler. It
        # should also bubble up to the root logger so we only need to
        # use it for ERROR or CRITICAL messages.

        self.emaillogger = logging.getLogger('email')
        self.emaillogger.setLevel(logging.ERROR)
        emailhandler = SMTPHandler(self.mail_host,
                                   self.mail_username,
                                   self.admin_toaddrs,
                                   self.admin_subject,
                                   credentials=(self.mail_username,
                                                self.mail_password),
                                   secure=())
        self.emaillogger.addHandler(emailhandler)

        # TODO(bc) Set up user email logger.
        # the handler has the following attributes we may be able
        # to overwrite per call.
  	#        self.toaddrs = toaddrs
        #        self.subject = subject

        self.userlogger = logging.getLogger('user')
        self.userlogger.propagate = False
        self.userlogger.setLevel(logging.INFO)
        self.userhandler = SMTPHandler(self.mail_host,
                                       self.mail_username,
                                       self.admin_toaddrs,
                                       'user subject',
                                       credentials=(self.mail_username,
                                                    self.mail_password),
                                   secure=())
        self.userlogger.addHandler(self.userhandler)

    def notify_user(self, user, subject):
        """Set the useremail handler's to address and subject fields
        and return a reference to the userlogger object."""
        self.userhandler.toaddrs = [user]
        self.userhandler.subject = subject
        return self.userlogger

    def purge_job(self, jobid):
        """Purge the job whose id is jobid along with all of the
        linked locations, speeds, and urls.
        """
        jobparm = {'jobid': jobid}
        try:
            self.cursor.execute('delete from urls where jobid=:jobid',
                                jobparm)
            self.cursor.execute('delete from speeds where jobid=:jobid',
                                jobparm)
            self.cursor.execute('delete from locations where jobid=:jobid',
                                jobparm)
            self.cursor.execute('delete from jobs where id=:jobid',
                                jobparm)
            self.connection.commit()
        except sqlite3.OperationalError:
            self.emaillogger.exception('purge_job:: %s' % jobid)
        finally:
            if jobid == jobid:
                self.job = None

    def check_build(self, build):
        """Check the build url to see if build is available. build can
        be either a direct link to a build or a link to a directory
        containing the build. If the build is available, then
        check_build will return the actual url to the build.
        """
        # TODO(bc) if build is a directory, then we need to pick the
        # latest url.

        buildurl = None
        re_builds = re.compile(r"firefox-([0-9]+).*\.win32\.installer\.exe")
        httplib = httplib2.Http();

        if not build.endswith("/"):
            # direct url to a build implies the build is available now.
            buildurl = build
        else:
            try:
                builddir_resp, builddir_content = httplib.request(build, "GET")
                if builddir_resp.status == 200:
                    builddir_soup = BeautifulSoup.BeautifulSoup(builddir_content)
                    for build_link in builddir_soup.findAll("a"):
                        match = re_builds.match(build_link.get("href"))
                        if match:
                            buildurl = "%s%s" % (build, build_link.get("href"))
                            break
            except:
                # Which exceptions here? from httplib, BeautifulSoup
                self.emaillogger.exception("Error checking build")
                buildurl = None

        if buildurl:
            buildurl_resp, buildurl_content = httplib.request(buildurl, "HEAD")
            if buildurl_resp.status != 200:
                buildurl = None

        return buildurl

    def process_job(self):
        """Get the oldest pending job and start it up.
        """
        try:
            self.cursor.execute(
                "select * from jobs where status = 'pending' order by started")
            jobrow = self.cursor.fetchone()
        except sqlite3.OperationalError:
            self.emaillogger.exception("Finding pending jobs.")
            raise

        if not jobrow:
            return

        (jobid, email, build, label, runs, status, started, timestamp) = jobrow
        timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        status = "running"
        self.logger.debug("jobid: %s, email: %s, build: %s, label: %s, "
                          "runs; %s,status: %s, started: %s, timestamp: %s" %
                          (jobid, email, build, label,
                           runs, status, started, timestamp))
        try:
            self.cursor.execute(
                "update jobs set build=:build, status=:status, "
                "timestamp=:timestamp where id=:jobid",
                {"jobid": jobid, "build": build, "status": status,
                 "timestamp": timestamp})
            self.connection.commit()
        except sqlite3.OperationalError:
            self.emaillogger.exception("Error updating job %s" % jobid)
            self.notify_user(email, 'Your webpagetest job failed').error(
            """Your webpagetest job %s for build %s, label %s failed due to
            SQLErrors. Please contact your administrators %s for help.""" %
            (jobid, build, label, self.admin_toaddrs))
            raise

        self.job = {
            'id' : jobid,
            'email': email,
            'build': build,
            'label': label,
            'runs': runs,
            'status': status,
            'started': started,
            'timestamp': timestamp
            }
        self.download_build()

        locations = self.get_locations()
        speeds = self.get_speeds()
        urls = self.get_urls()

        for location in locations:
            self.process_location(location, speeds, urls)

        msg_subject = "Your webpagetest job %s build %s, label %s completed.\n\n" % \
            (jobid, build, label)
        msg_body = "Results for job %s build %s, label %s are complete.\n\n" % \
            (jobid, build, label)
        self.notify_user(email, msg_subject).info(msg_body)
        self.purge_job(jobid)

    def download_build(self):
        """Download a build to the webpagetest server and
        update the firefox.dat file.
        """
        self.logger.debug("downloading build: %s" % self.job["build"])

        try:
            if os.path.exists(self.firefoxpath):
                os.unlink(self.firefoxpath)

            urllib.urlretrieve(self.job["build"], self.firefoxpath)
            #fh = open(firefoxpath)
            #md5sum = md5.new()
            #md5sum.update(fh.read())
            #md5digest = md5sum.hexdigest()
            #fh.close()
        except IOError:
            self.emaillogger.exception("IOError retrieving build: %s." %
                                       self.job.__str__())
            # delete row? attempt again up to a maximum number of tries?
            self.notify_user(self.job["email"], 'Your webpagetest job failed').error(
            """Your webpagetest job %s for build %s, label %s failed due to
            a download error. Please contact your administrators %s for help.""" %
            (self.job["id"], self.job["build"], self.job["label"], self.admin_toaddrs))
            raise
        try:
            builddat = open(self.firefoxdatpath, "w")
            builddat.write("browser=Firefox\n")
            builddat.write("url=http://%s/installers/browsers/"
                           "firefox-installer.exe\n" % self.server)
            #builddat.write("md5=%s\n" % md5digest)
            # need to create a random version here so wpt will install it.
            builddat.write("version=%d\n" % int(100*random.random()))
            builddat.write("command=firefox-installer.exe "
                           "/INI=c:\\webpagetest\\firefox.ini\n")
            builddat.write("update=1\n")
            builddat.close()
        except IOError:
            self.emaillogger.exception("IOError writing firefox.dat: %s." %
                                       self.job.__str__())
            self.notify_user(self.job["email"], 'Your webpagetest job failed').error(
            """Your webpagetest job %s for build %s, label %s failed due to
            a download error. Please contact your administrators %s for help.""" %
            (self.job["id"], self.job["build"], self.job["label"], self.admin_toaddrs))
            raise

        # delay after updating firefox.dat to give the clients time to
        # check for the updated build.
        time.sleep(120)

    def get_locations(self):
        """Get the locations for the current job.
        """
        try:
            self.cursor.execute("select location from locations "
                                "where jobid=:jobid", {"jobid":self.job["id"]})
            locationrows = self.cursor.fetchall()
            locations = [locationrow[0] for locationrow in locationrows]
        except sqlite3.OperationalError:
            self.emaillogger.exception("SQLError collecting locations: %s." %
                                       self.job.__str__())
            self.notify_user(self.job["email"], 'Your webpagetest job failed').error(
            """Your webpagetest job %s for build %s, label %s failed due to
            an SQLError getting locations. Please contact your administrators %s for help.""" %
            (self.job["id"], self.job["build"], self.job["label"], self.admin_toaddrs))
            raise
        return locations

    def get_speeds(self):
        """Get the speeds for the current job.
        """
        try:
            self.cursor.execute("select speed from speeds where jobid=:jobid",
                                {"jobid":self.job["id"]})
            speedrows = self.cursor.fetchall()
            speeds = [speedrow[0] for speedrow in speedrows]
        except sqlite3.OperationalError:
            self.emaillogger.exception("SQLError: collecting speeds: %s." %
                                       self.job.__str__())
            self.notify_user(self.job["email"], 'Your webpagetest job failed').error(
            """Your webpagetest job %s for build %s, label %s failed due to
            an SQLError getting speeds. Please contact your administrators %s for help.""" %
            (self.job["id"], self.job["build"], self.job["label"], self.admin_toaddrs))
            raise
        return speeds

    def get_urls(self):
        """Get the urls for the current job.
        """
        try:
            self.cursor.execute("select url from urls where jobid=:jobid",
                                {"jobid": self.job["id"]})
            urlrows = self.cursor.fetchall()
            # convert to an array of urls rather than an array of tuples of urls
            urls = [urlrow[0] for urlrow in urlrows]
        except sqlite3.OperationalError:
            self.emaillogger.exception("SQLError: collecting urls: %s." %
                                       self.job.__str__())
            self.notify_user(self.job["email"], 'Your webpagetest job failed').error(
            """Your webpagetest job %s for build %s, label %s failed due to
            an SQLError getting urls. Please contact your administrators %s for help.""" %
            (self.job["id"], self.job["build"], self.job["label"], self.admin_toaddrs))
            raise
        return urls

    def process_location(self, location, speeds, urls):
        """Submit jobs for this location for each speed and url.
        """
        self.logger.debug("process_location: %s" % location)

        # We can submit any number of speeds and urls for a given
        # location, but we can't submit more than one location at
        # a time since it might affect the network performance if
        # multiple machines are downloading builds, running tests
        # simultaneously.

        test_url_map = {}
        test_speed_map = {}
        for speed in speeds:
            self.logger.debug("process_location: location: %s, speed: %s" %
                              (location, speed))

            # The location parameter submitted to wpt's
            # runtest.php is of the form:
            # location:browser.connectivity

            wpt_parameters = {
                'f': 'xml',
                'private': 0,
                'priority': 6,
                'video': 1,
                'fvonly': 0,
                'label': self.job["label"],
                'runs': self.job["runs"],
                'location': '%s.%s' % (location, speed),
                'mv': 0,
                'k': self.api_key,
            }

            # TODO(bc) Replace wpt_batch_lib.SubmitBatch
            self.logger.debug(
                "submitting batch: email: %s, build: %s, "
                "label: %s, location: %s, speed: %s, urls: %s, "
                "wpt_parameters: %s, server: %s"  % (
                    self.job["email"], self.job["build"],
                    self.job["label"], location, speed, urls,
                    wpt_parameters, self.server))
            partial_test_url_map = wpt_batch_lib.SubmitBatch(
                urls,
                wpt_parameters,
                'http://%s/' % self.server)
            self.logger.debug("partial_test_url_map: %s" % partial_test_url_map)
            accepted_urls = partial_test_url_map.values()
            for url in urls:
                if url not in accepted_urls:
                    logging.warn('url %s was not accepted.', url)
            test_url_map.update(partial_test_url_map)
            for test_id in partial_test_url_map.keys():
                test_speed_map[test_id] = speed

        test_msg_map = {}
        pending_test_url_map = dict(test_url_map)

        # terminate the job after each url has been given 10 minutes to complete.
        terminate_time = (datetime.datetime.now() +
                          datetime.timedelta(minutes=(len(accepted_urls)*10)))

        while pending_test_url_map:
            self.logger.debug("pending_test_url_map: %s" % pending_test_url_map)
            if datetime.datetime.now() > terminate_time:
                test_ids = [test_id for test_id in pending_test_url_map]
                for test_id in test_ids:
                    del pending_test_url_map[test_id]
                    test_msg_map[test_id] = 'timed out'
                continue

            # TODO(bc) Replace wpt_batch_lib.CheckBatchStatus
            self.logger.debug(
                "CheckBatchStatus: email: %s, build: %s, label: %s, "
                "location: %s, speed: %s, urls: %s" % (
                    self.job["email"], self.job["build"], self.job["label"],
                    location, speed, urls))
            test_status_map = wpt_batch_lib.CheckBatchStatus(
                pending_test_url_map.keys(),
                server_url='http://%s/' % self.server)
            self.logger.debug("CheckBatchStatus: %s" % test_status_map)
            for test_id, test_status in test_status_map.iteritems():
                test_status = int(test_status)
                if test_status == 100:
                    test_status_text = "started"
                elif test_status == 101:
                    test_status_text = "waiting"
                elif test_status == 200:
                    test_status_text = "complete"
                    del pending_test_url_map[test_id]
                elif test_status == 400 or test_status == 401:
                    test_status_text = "not found"
                    del pending_test_url_map[test_id]
                    test_msg_map[test_id] = 'not found.'
                elif test_status == 402:
                    test_status_text = "cancelled"
                    del pending_test_url_map[test_id]
                    test_msg_map[test_id] = 'cancelled.'
                else:
                    test_status_text = "unexpected failure"
                    del pending_test_url_map[test_id]
                    test_msg_map[test_id] = 'failed with unexpected status %s' % test_status
                self.logger.debug("processing test status %s %s %s" %
                                  (test_id, test_status, test_status_text))

            if pending_test_url_map:
                self.logger.debug("Finished checking batch status, "
                                  "sleeping 60 seconds...")
                time.sleep(60)

        messages = ''
        for test_id, test_message in test_msg_map.iteritems():
            messages += 'Test %s for url %s: %s\n' % (test_id, test_url_map[test_id], test_msg_map[test_id])
            del test_url_map[test_id]
        if messages:
            messages = '\n' + messages

        # 'GetJSONResult'
        test_results_map = {}
        for test_id in test_url_map.keys():
            self.logger.debug("Getting result for test %s" % test_id)
            result_url = 'http://%s/jsonResult.php?test=%s' % (self.server, test_id)
            self.logger.debug("result_url %s" % result_url)
            result_response = urllib.urlopen(result_url)
            if result_response.getcode() == 200:
                test_results_map[test_id] = json.loads(result_response.read())
            else:
                messages += 'failed to retrieve results for Test %s url %s' % (test_id, test_url_map[test_id])

        self.emaillogger.warn(messages)
        self.process_test_results(location, test_speed_map, test_url_map, test_results_map, messages)

    def process_test_results(self, location, test_speed_map, test_url_map, test_results_map, messages):
        """Process test results, notifying user of the results.
        """
        # TODO(bc) submit to datazilla.

        msg_subject = "Your webpagetest job %s build %s, label %s for location %s, completed.\n\n" % \
            (self.job["id"], self.job["build"], self.job["label"], location)
        msg_body = "Results for job %s build %s, label %s for location %s\n\n" % (self.job["id"],
                                                                                  self.job["build"],
                                                                                  self.job["label"],
                                                                                  location)
        msg_body_map = {}

        result_file = open('results.txt', 'a+')
        result_file.write(messages)
        for test_id, test_result in test_results_map.iteritems():
            url = test_url_map[test_id]
            speed = test_speed_map[test_id]
            msg_body_map[url + speed] = "Url: %s, Speed: %s, Result: http://%s/result/%s/\n" % (url, speed, self.server, test_id)
            result_file.write('Test %s, Speed %s, url %s\n' %
                              (test_id, test_speed_map[test_id], test_url_map[test_id]))
            result_file.write(json.dumps(test_result) + '\n')
        result_file.close()

        msg_body_keys = msg_body_map.keys()
        msg_body_keys.sort()
        for msg_body_key in msg_body_keys:
            msg_body += msg_body_map[msg_body_key]
        if messages:
            msg_body += "\n\nMessages: %s\n" % messages
        self.notify_user(self.job["email"], msg_subject).info(msg_body)

    def check_waiting_jobs(self):
        """Check waiting jobs that are older than check_minutes or
        that have not been checked yet to see if builds are
        available. If they are available, switch them to pending.
        """
        check_threshold = (datetime.datetime.now() -
                           datetime.timedelta(minutes=self.check_minutes)).strftime("%Y-%m-%dT%H:%M:%S")
        try:
            self.cursor.execute(
                "select * from jobs where status = 'waiting' and "
                "(timestamp is NULL or timestamp < :check_threshold)",
                {"check_threshold": check_threshold})
            jobrows = self.cursor.fetchall()
        except sqlite3.OperationalError:
            self.emaillogger.exception("SQLError: checking_waiting_jobs.")
            raise

        for jobrow in jobrows:
            (jobid, email, build, label, runs, status, started, timestamp) = jobrow
            self.logger.debug("checking_waiting_jobs: "
                              "jobid: %s, email: %s, build: %s, label: %s, "
                              "runs: %s, status: %s, "
                              "started: %s, timestamp: %s" %
                              (jobid, email, build, label,
                               runs, status,
                               started, timestamp))
            buildurl = self.check_build(build)
            if buildurl:
                status = "pending"
                build = buildurl
            try:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                self.cursor.execute("update jobs set build=:build, "
                               "status=:status, timestamp=:timestamp "
                               "where id=:jobid",
                               {"jobid": jobid, "build": build,
                                "status": status, "timestamp": timestamp})
                self.connection.commit()
            except sqlite3.OperationalError:
                self.emaillogger.exception("SQLError: checking_waiting_jobs: "
                                           "updating job: "
                                           "jobid: %s, email: %s, build: %s, "
                                           "label: %s, "
                                           "runs: %s, status: %s, "
                                           "started: %s, timestamp: %s" %
                                           (jobid, email, build, label,
                                            runs, status,
                                            started, timestamp))
                raise

    def check_running_jobs(self):
        """Check the running job if any.
        """
        try:
            self.cursor.execute("select * from jobs where status = 'running'")
            jobrows = self.cursor.fetchall()
        except sqlite3.OperationalError:
            self.emaillogger.exception("Checking running job.")
            raise

        if jobrows:
            ### We should never get here unless we crashed while processing
            ### a job. Lets just delete any jobs with 'running' status and
            ### notify the user.
            for jobrow in jobrows:
                # send email to user then delete job
                (jobid, email, build, label, runs, status, started, timestamp) = jobrow
                self.purge_job(jobid)

if __name__ == '__main__':

    from optparse import OptionParser

    parser = OptionParser()

    parser.add_option('--database', action='store', type='string', dest='database',
                      default='jobmanager.sqlite', help='Path to sqlite3 database file. '
                      'Defaults to jobmanager.sqlite in current directory.')

    parser.add_option('--log', action='store', type='string', dest='log',
                      default='monitor.log', help='Path to monitor log file. '
                      'Defaults to monitor.log in current directory.')

    parser.add_option('--settings', action='store', type='string', dest='settings',
                      default='settings.ini', help='Path to configuration file. '
                      'Defauls to settings.ini in current directory.')

    (options, args) = parser.parse_args()

    if not os.path.exists(options.settings):
        print 'Settings file %s does not exist' % options.settings
        exit(2)

    jm = JobMonitor(options)

    while True:
        jm.check_waiting_jobs()
        jm.check_running_jobs()
        jm.process_job()
        time.sleep(jm.sleep_time)
