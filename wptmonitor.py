#!/usr/bin/env python
# This Source Code is subject to the terms of the Mozilla Public License
# version 2.0 (the "License"). You can obtain a copy of the License at
# http://mozilla.org/MPL/2.0/.

import ConfigParser
import datetime
import httplib2
import json
import logging
#import md5
import os
import random
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib

from optparse import OptionParser
from dzclient import DatazillaRequest, DatazillaResult

import BeautifulSoup

from logging.handlers import TimedRotatingFileHandler
from emailhandler import SMTPHandler
from daemonize import Daemon

class Job(object):
    def __init__(self, jobmonitor, jobid, email, build, label, runs, tcpdump,
                 video, datazilla, script, status, started, timestamp):
        self.jm = jobmonitor
        self.id = jobid
        self.email = email
        self.build = build
        self.label = label
        self.runs = runs
        self.tcpdump = tcpdump
        self.video = video
        self.datazilla = datazilla
        self.script = script.replace('\\t', '\t').replace('\\n', '\n')
        if jobid:
            self.locations = self.get_locations(jobmonitor, jobid)
            self.speeds = self.get_speeds(jobmonitor, jobid)
            self.urls = self.get_urls(jobmonitor, jobid)
        else:
            self.locations = None
            self.speeds = None
            self.urls = None
        self.status = status
        self.started = started
        self.timestamp = timestamp

    # Don't capture exceptions in get_locations, get_speeds or get_urls.
    # We will catch any exceptions thrown here and clean up the job from
    # the caller. Otherwise we end up trying to deal deleting a job from
    # inside the Job constructor.
    def get_locations(self, jobmonitor, jobid):
        """Get the locations for the specified job.
        """
        jobmonitor.cursor.execute("select location from locations "
                                  "where jobid=:jobid", {"jobid":jobid})
        locationrows = jobmonitor.cursor.fetchall()
        locations = [locationrow[0] for locationrow in locationrows]
        return locations

    def get_speeds(self, jobmonitor, jobid):
        """Get the speeds for the specified job.
        """
        jobmonitor.cursor.execute("select speed from speeds where jobid=:jobid",
                                  {"jobid":jobid})
        speedrows = jobmonitor.cursor.fetchall()
        speeds = [speedrow[0] for speedrow in speedrows]
        return speeds

    def get_urls(self, jobmonitor, jobid):
        """Get the urls for the specified job.
        """
        jobmonitor.cursor.execute("select url from urls where jobid=:jobid",
                                  {"jobid": jobid})
        urlrows = jobmonitor.cursor.fetchall()
        # convert to an array of urls rather than an array of tuples of urls
        urls = [urlrow[0] for urlrow in urlrows]
        return urls

class JobMonitor(Daemon):
    def __init__(self, options, createdb=False):

        super(JobMonitor, self).__init__(options)

        self.database = options.database
        self.job = None

        config = ConfigParser.RawConfigParser()
        config.readfp(open(options.settings))

        self.server = config.get("server", "server")
        self.results_server = config.get("server", "results_server")
        self.time_limit = config.getint("server", "time_limit")
        self.sleep_time = config.getint("server", "sleep_time")
        self.check_minutes = config.getint("server", "check_minutes")
        try:
            self.port = config.getint("server", "port")
        except ConfigParser.Error:
            self.port = 8051
        self.api_key = config.get("server", "api_key")
        self.firefoxpath = config.get("server", "firefoxpath")
        self.firefoxdatpath = config.get("server", "firefoxdatpath")
        self.build_name = None
        self.build_version = None
        self.build_id = None
        self.build_branch = None
        self.build_revision = None

        self.default_locations = config.get("defaults", "locations").split(",")
        self.default_urls = config.get("defaults", "urls").split(",")

        self.admin_toaddrs = config.get("admin", "admin_toaddrs").split(",")
        self.admin_subject = config.get("admin", "admin_subject")
        self.mail_username = config.get("mail", "username")
        self.mail_password = config.get("mail", "password")
        self.mail_host = config.get("mail", "mailhost")

        self.oauth_key = config.get("datazilla", "oauth_consumer_key")
        self.oauth_secret = config.get("datazilla", "oauth_consumer_secret")

        self.admin_loglevel = logging.DEBUG
        try:
            self.admin_loglevel = getattr(logging,
                                          config.get("admin",
                                                     "admin_loglevel"))
        except AttributeError:
            pass
        except ConfigParser.Error:
            pass

        # Set up the root logger to log to a daily rotated file log.
        self.logfile = options.log
        self.logger = logging.getLogger("wpt")
        self.logger.setLevel(self.admin_loglevel)
        filehandler = TimedRotatingFileHandler(self.logfile,
                                               when="D",
                                               interval=1,
                                               backupCount=7,
                                               encoding=None,
                                               delay=False,
                                               utc=False)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        filehandler.setFormatter(formatter)
        self.logger.addHandler(filehandler)

        # Set up the administrative logger with an SMTP handler. It
        # should also bubble up to the root logger so we only need to
        # use it for ERROR or CRITICAL messages.

        self.emaillogger = logging.getLogger("wpt.email")
        self.emaillogger.setLevel(logging.ERROR)
        self.emailhandler = SMTPHandler(self.mail_host,
                                        self.mail_username,
                                        self.admin_toaddrs,
                                        self.admin_subject,
                                        credentials=(self.mail_username,
                                                     self.mail_password),
                                        secure=())
        self.emaillogger.addHandler(self.emailhandler)

        self.userlogger = logging.getLogger("user")
        self.userlogger.propagate = False
        self.userlogger.setLevel(logging.INFO)
        self.userhandler = SMTPHandler(self.mail_host,
                                       self.mail_username,
                                       self.admin_toaddrs,
                                       "user subject",
                                       credentials=(self.mail_username,
                                                    self.mail_password),
                                   secure=())
        self.userlogger.addHandler(self.userhandler)

        self.automatic_jobs = []
        job_names = []
        try:
            job_names = config.get("automatic", "jobs").split(",")
        except ConfigParser.Error:
            pass
        for job_name in job_names:
            automatic_job = {}
            self.automatic_jobs.append(automatic_job)
            automatic_job["email"] = config.get(job_name, "email")
            automatic_job["label"] = config.get(job_name, "label")
            automatic_job["build"] = config.get(job_name, "build")
            automatic_job["urls"] = config.get(job_name, "urls").split(",")
            automatic_job["locations"] = config.get(job_name, "locations").split(",")
            automatic_job["speeds"] = config.get(job_name, "speeds").split(",")
            automatic_job["runs"] = config.get(job_name, "runs")
            automatic_job["tcpdump"] = config.get(job_name, "tcpdump")
            automatic_job["video"] = config.get(job_name, "video")
            automatic_job["datazilla"] = config.get(job_name, "datazilla")
            automatic_job["script"] = config.get(job_name, "script")
            automatic_job["hour"] = config.getint(job_name, "hour")
            # If the current hour before the scheduled hour for
            # the job, force its submission today. Otherwise, wait until
            # tomorrow to submit the job.
            automatic_job["datetime"] = datetime.datetime.now()
            if automatic_job["datetime"].hour <= automatic_job["hour"]:
                automatic_job["datetime"] -= datetime.timedelta(days=1)

        if os.path.exists(self.database):
            try:
                self.connection = sqlite3.connect(self.database)
                self.connection.execute("PRAGMA foreign_keys = ON;")
                self.cursor = self.connection.cursor()
            except sqlite3.OperationalError:
                self.notify_admin_logger("Failed to start").exception(
                    "Could not get database connection " +
                    "to %s" % self.database)
                exit(2)
        elif not createdb:
                self.notify_admin_logger("Failed to start").error(
                    "database file %s does not exist" %
                    self.database)
                exit(2)
        else:
            try:
                self.connection = sqlite3.connect(options.database)
                self.connection.execute("PRAGMA foreign_keys = ON;")
                self.cursor = self.connection.cursor()
                self.cursor.execute("create table jobs ("
                                    "id integer primary key autoincrement, "
                                    "email text, "
                                    "build text, "
                                    "label text, "
                                    "runs text, "
                                    "tcpdump text, "
                                    "video text, "
                                    "datazilla text, "
                                    "script text, "
                                    "status text, "
                                    "started text, "
                                    "timestamp text"
                                    ")"
                                    )
                self.connection.commit()
                self.cursor.execute("create table locations ("
                                    "id integer primary key autoincrement, "
                                    "location text, "
                                    "jobid references jobs(id)"
                                    ")"
                                    )
                self.connection.commit()
                self.cursor.execute("create table speeds ("
                                    "id integer primary key autoincrement, "
                                    "speed text, "
                                    "jobid references jobs(id)"
                                    ")"
                                    )
                self.connection.commit()
                self.cursor.execute("create table urls ("
                                    "id integer primary key autoincrement, "
                                    "url text, "
                                    "jobid references jobs(id)"
                                    ")"
                                    )
                self.connection.commit()
            except sqlite3.OperationalError:
                self.notify_admin_logger("Failed to start").exception(
                    "SQLError creating schema in " +
                    "database %s" % options.database)
                exit(2)

    def set_job(self, jobid, email, build, label, runs, tcpdump,
                 video, datazilla, script, status, started, timestamp):
        try:
            self.job = Job(self, jobid, email, build, label, runs, tcpdump,
                           video, datazilla, script, status, started, timestamp)
        except:
            self.notify_admin_exception("Error setting job")
            self.notify_user_exception(self.job.email,
                                       "Error setting job")
            self.purge_job(jobid)

    def create_job(self, email, build, label, runs, tcpdump,
                   video, datazilla, script,
                   locations, speeds, urls):
        self.set_job(None, email, build, label, runs, tcpdump, video, datazilla,
                     script, None, None, None)
        self.job.locations = locations
        self.job.speeds = speeds
        self.job.urls = urls

        # If the build is a simple hexadecimal string, convert it into
        # a url for the equivalent try build for the given email.
        reHex = re.compile(r'[a-zA-Z0-9]*$')
        if reHex.match(build):
            self.job.build = build = "http://ftp.mozilla.org/pub/mozilla.org/"\
                             "firefox/try-builds/%s-%s/try-win32/" % (email,
                                                                      build)

        try:
            self.cursor.execute(
                "insert into jobs(email, build, label, runs, tcpdump, video, "
                "datazilla, script, status, started) "
                "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (email, build, label, runs, tcpdump, video, datazilla, script,
                 "waiting",
                 datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
            self.connection.commit()
            self.job.id = jobid = self.cursor.lastrowid
        except sqlite3.OperationalError:
            self.notify_admin_exception("Error inserting job")
            self.notify_user_exception(email, "Error inserting job")
            raise

        for location in locations:
            try:
                self.cursor.execute(
                    "insert into locations(location, jobid) "
                    "values (?, ?)",
                    (location, jobid))
                self.connection.commit()
            except sqlite3.OperationalError:
                self.notify_admin_exception("Error inserting location")
                self.notify_user_exception(email, "Error inserting location")
                self.purge_job(jobid)
                raise

        for speed in speeds:
            try:
                self.cursor.execute(
                    "insert into speeds(speed, jobid) values (?, ?)",
                    (speed, jobid))
                self.connection.commit()
            except sqlite3.OperationalError:
                msg = ("SQLError inserting speed: email: %s, build: %s, "
                       "label: %s, location: %s" % (email, build, label, speed))
                self.notify_admin_exception("Error inserting speed")
                self.notify_user_exception(email, "Error inserting speed")
                self.purge_job(jobid)
                raise

        for url in urls:
            try:
                self.cursor.execute(
                    "insert into urls(url, jobid) values (?, ?)",
                    (url, jobid))
                self.connection.commit()
            except sqlite3.OperationalError:
                self.notify_admin_exception("Error inserting url")
                self.notify_user_exception(email, "Error inserting url")
                self.purge_job(jobid)
                raise

        self.notify_user_info(email, "job submitted")

    def job_email_boilerplate(self, subject, message=None):
        if not message:
            message = ""
        if not self.job:
            job_message = ""
        else:
            job_message = """
Job:       %(id)s
Label:     %(label)s
Build:     %(build)s
Locations: %(locations)s
Urls:      %(urls)s
Speeds:    %(speeds)s
Runs:      %(runs)s
tcpdump:   %(tcpdump)s
video:     %(video)s
datazilla: %(datazilla)s
script:    %(script)s
Status:    %(status)s
""" % self.job.__dict__
        job_message = "%s\n\n%s\n\n%s\n\n" % (subject, job_message, message)
        return job_message

    def notify_user_logger(self, user, subject):
        """Set the userlogger's handler to address and subject fields
        and return a reference to the userlogger object."""
        if self.job:
            subject = "[WebPagetest] Job %s Label %s %s" % (self.job.id,
                                                            self.job.label,
                                                            subject)
        else:
            subject = "[WebPagetest] %s" % subject
        self.userhandler.toaddrs = [user]
        self.userhandler.subject = subject
        return self.userlogger

    def notify_admin_logger(self, subject):
        """Set the emaillogger's handler subject field
        and return a reference to the emaillogger object."""
        if self.job:
            subject = "[WebPagetest] Job %s Label %s %s" % (self.job.id,
                                                            self.job.label,
                                                            subject)
        else:
            subject = "[WebPagetest] %s" % subject
        self.emailhandler.subject = subject
        return self.emaillogger

    def notify_user_info(self, user, subject, message=None):
        job_message = self.job_email_boilerplate(subject, message)
        self.notify_user_logger(user, subject).info(job_message)

    def notify_user_exception(self, user, subject, message=None):
        job_message = self.job_email_boilerplate(subject, message)
        contact_message = ("Please contact your administrators %s for help." %
                           self.admin_toaddrs)
        job_message = "%s%s" % (job_message, contact_message)
        self.notify_user_logger(user, subject).exception(job_message)

    def notify_user_error(self, user, subject, message=None):
        job_message = self.job_email_boilerplate(subject, message)
        contact_message = ("Please contact your administrators %s for help." %
                           self.admin_toaddrs)
        job_message = "%s%s" % (job_message, contact_message)
        self.notify_user_logger(user, subject).error(job_message)

    def notify_admin_info(self, subject, message=None):
        job_message = self.job_email_boilerplate(subject, message)
        self.notify_admin_logger(subject).info(job_message)

    def notify_admin_exception(self, subject, message=None):
        job_message = self.job_email_boilerplate(subject, message)
        self.notify_admin_logger(subject).exception(job_message)

    def notify_admin_error(self, subject, message=None):
        job_message = self.job_email_boilerplate(subject, message)
        self.notify_admin_logger(subject).error(job_message)

    def purge_job(self, jobid):
        """Purge the job whose id is jobid along with all of the
        linked locations, speeds, and urls.
        """
        if not jobid:
            return

        jobparm = {"jobid": jobid}
        try:
            self.cursor.execute("delete from urls where jobid=:jobid",
                                jobparm)
            self.cursor.execute("delete from speeds where jobid=:jobid",
                                jobparm)
            self.cursor.execute("delete from locations where jobid=:jobid",
                                jobparm)
            self.cursor.execute("delete from jobs where id=:jobid",
                                jobparm)
            self.connection.commit()
        except sqlite3.OperationalError:
            self.notify_admin_exception("Exception purging job %s" % jobid)
        finally:
            if self.job and self.job.id == jobid:
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
            except:
                # Which exceptions here? from httplib, BeautifulSoup
                self.notify_admin_exception("Error checking build")
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
            self.notify_admin_exception("Error finding pending jobs")
            raise

        if not jobrow:
            return

        (jobid, email, build, label, runs, tcpdump, video, datazilla, script,
         status, started, timestamp) = jobrow
        self.set_job(jobid, email, build, label, runs, tcpdump, video, datazilla,
                     script, status, started, timestamp)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        self.job.status = status = "running"
        self.logger.debug("jobid: %s, email: %s, build: %s, label: %s, "
                          "runs; %s, tcpdump: %s, video: %s, datazilla: %s, "
                          "script: %s, status: %s, started: %s, timestamp: %s" %
                          (jobid, email, build, label,
                           runs, tcpdump, video, datazilla, script, status,
                           started, timestamp))
        try:
            self.cursor.execute(
                "update jobs set build=:build, status=:status, "
                "timestamp=:timestamp where id=:jobid",
                {"jobid": jobid, "build": build, "status": status,
                 "timestamp": timestamp})
            self.connection.commit()
            self.notify_user_info(email, "job is running")
        except sqlite3.OperationalError:
            self.notify_admin_exception("Error updating running job")
            self.notify_user_exception(email, "Error updating running job")
            self.purge_job(jobid)
            return

        if not self.download_build():
            self.purge_job(jobid)
            return

        for location in self.job.locations:
            self.process_location(location)

        self.job.status = "completed"
        self.notify_user_info(email, "job completed.")
        self.purge_job(jobid)

    def download_build(self):
        """Download a build to the webpagetest server and
        update the firefox.dat file.
        """
        self.logger.debug("downloading build: %s" % self.job.build)

        try:
            if os.path.exists(self.firefoxpath):
                os.unlink(self.firefoxpath)

            urllib.urlretrieve(self.job.build, self.firefoxpath)
            #fh = open(firefoxpath)
            #md5sum = md5.new()
            #md5sum.update(fh.read())
            #md5digest = md5sum.hexdigest()
            #fh.close()
        except IOError:
            self.notify_admin_exception("Error downloading build")
            self.notify_user_exception(self.job.email, "Error downloading build")
            return False
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
            self.notify_admin_exception("Error writing firefox.dat")
            self.notify_user_exception(self.job.email,
                                       "job failed")
            return False

        # Get information about the build by extracting the installer
        # to a temporary directory and parsing the application.ini file.
        tempdirectory = tempfile.mkdtemp()
        returncode = subprocess.call(["7z", "x", self.firefoxpath,
                                      "-o%s" % tempdirectory])
        appini = ConfigParser.RawConfigParser()
        appini.readfp(open("%s/core/application.ini" % tempdirectory))
        self.build_name = appini.get("App", "name")
        self.build_version = appini.get("App", "version")
        self.build_id = appini.get("App", "buildID")
        self.build_branch = os.path.basename(appini.get("App", "SourceRepository"))
        self.build_revision = appini.get("App", "SourceStamp")

        self.logger.debug("build_name: %s" % self.build_name)
        self.logger.debug("build_version: %s" % self.build_version)
        self.logger.debug("build_id: %s" % self.build_id)
        self.logger.debug("build_branch: %s" % self.build_branch)
        self.logger.debug("build_revision: %s" % self.build_revision)

        if returncode != 0:
            raise Exception("download_build: "
                            "error extracting build: rc=%d" % returncode)
        shutil.rmtree(tempdirectory)

        # delay after updating firefox.dat to give the clients time to
        # check for the updated build.
        time.sleep(120)
        return True

    def process_location(self, location):
        """Submit jobs for this location for each speed and url.
        """
        self.logger.debug("process_location: %s" % location)

        # We can submit any number of speeds and urls for a given
        # location, but we can't submit more than one location at
        # a time since it might affect the network performance if
        # multiple machines are downloading builds, running tests
        # simultaneously.

        def add_msg(test_msg_map, test_id, msg):
            if test_id not in test_msg_map:
                test_msg_map[test_id] = ""
            else:
                test_msg_map[test_id] += ", "
            test_msg_map[test_id] += msg

        messages = ""
        test_url_map = {}
        test_speed_map = {}
        for speed in self.job.speeds:
            self.logger.debug("process_location: location: %s, speed: %s" %
                              (location, speed))

            # The location parameter submitted to wpt's
            # runtest.php is of the form:
            # location:browser.connectivity

            wpt_parameters = {
                "f": "json",
                "private": 0,
                "priority": 6,
                "video": 1,
                "fvonly": 0,
                "label": self.job.label,
                "runs": self.job.runs,
                "tcpdump": self.job.tcpdump,
                "video": self.job.video,
                "location": "%s.%s" % (location, speed),
                "mv": 0,
                "script": self.job.script,
                "k": self.api_key,
            }

            self.logger.debug(
                "submitting batch: email: %s, build: %s, "
                "label: %s, location: %s, speed: %s, urls: %s, "
                "wpt_parameters: %s, server: %s"  % (
                    self.job.email, self.job.build,
                    self.job.label, location, speed, self.job.urls,
                    wpt_parameters, self.server))
            partial_test_url_map = {}
            for url in self.job.urls:
                if self.job.script:
                    wpt_parameters['script'] = '%s\nnavigate\t%s\n' % (self.job.script, url)

                else:
                    wpt_parameters['url'] = url
                request_url = 'http://%s/runtest.php?%s' % (self.server,
                                                            urllib.urlencode(wpt_parameters))
                response = urllib.urlopen(request_url)
                if response.getcode() == 200:
                    response_data = json.loads(response.read())
                    if response_data['statusCode'] == 200:
                        partial_test_url_map[response_data['data']['testId']] = url
            self.logger.debug("partial_test_url_map: %s" % partial_test_url_map)
            accepted_urls = partial_test_url_map.values()
            for url in self.job.urls:
                if url not in accepted_urls:
                    messages += "url %s was not accepted\n" % url
            test_url_map.update(partial_test_url_map)
            for test_id in partial_test_url_map.keys():
                test_speed_map[test_id] = speed

        test_msg_map = {}
        pending_test_url_map = dict(test_url_map)

        # terminate the job after each url has been sufficient time to:
        # load each url 3 times (once to prime wpr, once for first load,
        # once for second load) times the number of runs times the time
        # limit for a test.
        total_time_limit = (len(accepted_urls) * 3 * int(self.job.runs) *
                            self.time_limit)
        terminate_time = (datetime.datetime.now() +
                          datetime.timedelta(seconds=total_time_limit))

        while pending_test_url_map:
            self.logger.debug("pending_test_url_map: %s" % pending_test_url_map)
            if datetime.datetime.now() > terminate_time:
                test_ids = [test_id for test_id in pending_test_url_map]
                for test_id in test_ids:
                    del pending_test_url_map[test_id]
                    add_msg(test_msg_map, test_id,
                            "abandoned due to time limit.")
                continue
            self.logger.debug(
                "CheckBatchStatus: email: %s, build: %s, label: %s, "
                "location: %s, speed: %s, urls: %s" % (
                    self.job.email, self.job.build, self.job.label,
                    location, speed, self.job.urls))
            test_status_map = {}
            for test_id in pending_test_url_map.keys():
                request_url = 'http://%s/testStatus.php?f=json&test=%s' % (self.server,
                                                                           test_id)
                response = urllib.urlopen(request_url)
                if response.getcode() == 200:
                    response_data = json.loads(response.read())
                    test_status = response_data['statusCode']
                    test_status_map[test_id] = test_status
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
                        add_msg(test_msg_map, test_id, "not found")
                    elif test_status == 402:
                        test_status_text = "cancelled"
                        del pending_test_url_map[test_id]
                        add_msg(test_msg_map, test_id, "cancelled")
                    else:
                        test_status_text = "unexpected failure"
                        del pending_test_url_map[test_id]
                        add_msg(test_msg_map, test_id,
                                "failed with unexpected status %s" % test_status)
                    self.logger.debug("processing test status %s %s %s" %
                                      (test_id, test_status, test_status_text))

            if pending_test_url_map:
                self.logger.debug("Finished checking batch status, "
                                  "sleeping %d seconds..." % self.sleep_time)
                time.sleep(self.sleep_time)

        if messages:
            messages = "\n" + messages

        self.process_test_results(location, test_speed_map, test_url_map,
                                  test_msg_map, messages)

    def process_test_results(self, location, test_speed_map, test_url_map,
                             test_msg_map, messages):
        """Process test results, notifying user of the results.
        """
        build_name = ""
        build_version = ""
        build_revision = ""
        build_id = ""
        build_branch = ""

        msg_subject = "Results for location %s." % location
        msg_body = "Results for location %s\n\n" %  location
        msg_body_map = {}
        for test_id in test_url_map.keys():
            url = test_url_map[test_id]
            speed = test_speed_map[test_id]
            msg_body_key = url + speed

            try:
                msg = "Messages: %s\n\n" % test_msg_map[test_id]
            except KeyError:
                msg = ""
            msg_body_map[msg_body_key] = "\n".join([
                "Url: %s" % url,
                "Speed: %s" % speed,
                "Result: http://%s/result/%s/\n" % (self.results_server, test_id),
                "%s" % msg])
            result_url = "http://%s/jsonResult.php?test=%s" % (self.server,
                                                               test_id)
            self.logger.debug("Getting result for test %s result_url %s" %
                              (test_id, result_url))
            result_response = urllib.urlopen(result_url)
            if result_response.getcode() != 200:
                msg = "Failed to retrieve results from Webpagetest"
                msg_body_map[msg_body_key] += msg
                self.notify_admin_error(msg)
            else:
                test_result = json.loads(result_response.read())
                if test_result["statusCode"] == 200:
                    try:
                        datazilla_dataset = self.post_to_datazilla(test_result)[0]
                        if not build_version:
                            test_build_data = datazilla_dataset["test_build"]
                            build_name = test_build_data["name"]
                            build_version = test_build_data["version"]
                            build_revision = test_build_data["revision"]
                            build_id = test_build_data["id"]
                            build_branch = test_build_data["branch"]
                        wpt_data = datazilla_dataset["wpt_data"]
                        for view in "firstView", "repeatView":
                            view_data = wpt_data[view]
                            msg_body_map[msg_body_key] += "  %s:\n" % view
                            view_data_keys = view_data.keys()
                            view_data_keys.sort()
                            for data_key in view_data_keys:
                                msg_body_map[msg_body_key] += "    %s: %s\n" % (data_key, view_data[data_key])
                        msg_body_map[msg_body_key] += "\n"
                    except:
                        msg = "Error processing test result into datazilla"
                        msg_body_map[msg_body_key] += msg
                        self.notify_admin_exception(msg)
                if self.admin_loglevel == logging.DEBUG:
                    import os.path
                    logdir = os.path.dirname(self.logfile)
                    result_txt = open(os.path.join(logdir, "results-%s.txt" % test_id), "a+")
                    result_txt.write(msg_body)
                    result_txt.close()
                    result_json = open(os.path.join(logdir, "results-%s.json" % test_id), "a+")
                    result_json.write(json.dumps(test_result, indent=4, sort_keys=True) + "\n")
                    result_json.close()
                test_result = None

        if build_name:
            msg_body += "%s %s %s id: %s revision: %s\n\n" % (build_name,
                                                              build_version,
                                                              build_branch,
                                                              build_id,
                                                              build_revision)

        msg_body_keys = msg_body_map.keys()
        msg_body_keys.sort()
        if len(msg_body_keys) == 0:
            messages += "No results were found."
        else:
            for msg_body_key in msg_body_keys:
                msg_body += msg_body_map[msg_body_key]
        if messages:
            msg_body += "\n\n%s\n" % messages
        self.notify_user_info(self.job.email, msg_subject, msg_body)

    def post_to_datazilla(self, test_result):
        """ take test_results (json) and upload them to datazilla """

        # We will attach wpt_data to the datazilla result as a top
        # level attribute to store out of band data about the test.
        wpt_data = {
            "url": "",
            "firstView": {},
            "repeatView": {}
        }
        wpt_data["label"] = test_result["data"]["label"]
        submit_results = False
        if self.job.datazilla == "on":
            # Do not short circuit the function but collect
            # additional data for use in emailing the user
            # before returning.
            submit_results = True

        self.logger.debug('Submit results to datazilla: %s' % self.job.datazilla)
        wpt_data["connectivity"] = test_result["data"]["connectivity"]
        wpt_data["location"] = test_result["data"]["location"]
        wpt_data["url"] = test_result["data"]["url"]
        runs = test_result["data"]["runs"]

        # runs[0] is a dummy entry
        # runs[1]["firstView"]["SpeedIndex"]
        # runs[1]["repeatView"]["SpeedIndex"]
        # runs[1]["firstView"]["requests"][0]["headers"]["request"][2]
        #    "User-Agent: Mozilla/5.0 (Windows NT 5.1; rv:26.0) Gecko/20100101 Firefox/26.0 PTST/125"

        wpt_metric_keys = ['TTFB', 'render', 'docTime', 'fullyLoaded',
                           'SpeedIndex', 'SpeedIndexDT', 'bytesInDoc',
                           'requestsDoc', 'domContentLoadedEventStart',
                           'visualComplete']
        for wpt_key in wpt_metric_keys:
            for view in "firstView", "repeatView":
                wpt_data[view][wpt_key] = []

        if len(runs) == 1:
            raise Exception("post_to_datazilla: no runs")
        os_version = "unknown"
        os_name = "unknown"
        platform = "x86"
        reUserAgent = re.compile('User-Agent: Mozilla/5.0 \(Windows NT ([^;]*);.*')
        for run in runs:
            for wpt_key in wpt_metric_keys:
                for view in "firstView", "repeatView":
                    if not run[view]:
                        continue
                    if wpt_key in run[view]:
                        if run[view][wpt_key]:
                            wpt_data[view][wpt_key].append(run[view][wpt_key])
                    if os_name == "unknown":
                        try:
                            requests = run[view]["requests"]
                            if requests and len(requests) > 0:
                                request = requests[0]
                                if request:
                                    headers = request["headers"]
                                    if headers:
                                        request_headers = headers["request"]
                                        if request_headers:
                                            for request_header in request_headers:
                                                if "User-Agent" in request_header:
                                                    match = re.match(reUserAgent,
                                                                     request_header)
                                                    if match:
                                                        os_name = "WINNT"
                                                        os_version = match.group(1)
                                                        break
                        except KeyError:
                            pass

        machine_name = wpt_data["location"].split(":")[0]
        # limit suite name to 128 characters to match mysql column size
        suite_name = (wpt_data["location"] + "." + wpt_data["connectivity"])[:128]
        # limit {first,repeat}_name, to 255 characters to match mysql column size
        # leave protocol in the url in order to distinguish http vs https.
        first_name = wpt_data["url"][:252] + ":fv"
        repeat_name = wpt_data["url"][:252] + ":rv"
        result = DatazillaResult()
        result.add_testsuite(suite_name)
        result.add_test_results(suite_name, first_name, wpt_data["firstView"]["SpeedIndex"])
        result.add_test_results(suite_name, repeat_name, wpt_data["repeatView"]["SpeedIndex"])
        request = DatazillaRequest("https",
                                   "datazilla.mozilla.org",
                                   "webpagetest",
                                   self.oauth_key,
                                   self.oauth_secret,
                                   machine_name=machine_name,
                                   os=os_name,
                                   os_version=os_version,
                                   platform=platform,
                                   build_name=self.build_name,
                                   version=self.build_version,
                                   revision=self.build_revision,
                                   branch=self.build_branch,
                                   id=self.build_id)
        request.add_datazilla_result(result)
        datasets = request.datasets()
        for dataset in datasets:
            dataset["wpt_data"] = wpt_data
            if not submit_results:
                continue
            response = request.send(dataset)
            # print error responses
            if response.status != 200:
                # use lower-case string because buildbot is sensitive to upper case error
                # as in 'INTERNAL SERVER ERROR'
                # https://bugzilla.mozilla.org/show_bug.cgi?id=799576
                reason = response.reason.lower()
                self.logger.debug("Error posting to %s %s %s: %s %s" % (
                    wpt_data["url"], wpt_data["location"], wpt_data["connectivity"],
                    response.status, reason))
            else:
                res = response.read()
                self.logger.debug("Datazilla response for %s %s %s is: %s" % (
                    wpt_data["url"], wpt_data["location"], wpt_data["connectivity"],
                    res.lower()))
        return datasets

    def check_waiting_jobs(self):
        """Check waiting jobs that are older than check_minutes or
        that have not been checked yet to see if builds are
        available. If they are available, switch them to pending.
        """
        check_threshold = ((datetime.datetime.now() -
                           datetime.timedelta(minutes=self.check_minutes)).
                           strftime("%Y-%m-%dT%H:%M:%S"))
        try:
            self.cursor.execute(
                "select * from jobs where status = 'waiting' and "
                "(timestamp is NULL or timestamp < :check_threshold)",
                {"check_threshold": check_threshold})
            jobrows = self.cursor.fetchall()
        except sqlite3.OperationalError:
            self.notify_admin_exception("Error checking waiting jobs")
            raise

        for jobrow in jobrows:
            (jobid, email, build, label, runs, tcpdump, video, datazilla, script,
             status, started, timestamp) = jobrow
            self.set_job(jobid, email, build, label, runs, tcpdump,
                         video, datazilla, script, status, started, timestamp)

            self.logger.debug("checking_waiting_jobs: "
                              "jobid: %s, email: %s, build: %s, label: %s, "
                              "runs: %s, tcpdump: %s, video: %s, datazilla: %s, "
                              "script: %s, status: %s, started: %s, timestamp: %s" %
                              (jobid, email, build, label,
                               runs, tcpdump, video, datazilla, script, status,
                               started, timestamp))
            try:
                buildurl = self.check_build(build)
            except:
                self.notify_admin_exception("Build Error")
                self.notify_user_exception(email,
                                           "Build Error")
                self.purge_job(jobid)
                continue

            if buildurl:
                self.job.status = status = "pending"
                build = buildurl
            try:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                self.cursor.execute("update jobs set build=:build, "
                               "status=:status, timestamp=:timestamp "
                               "where id=:jobid",
                               {"jobid": jobid, "build": build,
                                "status": status, "timestamp": timestamp})
                self.connection.commit()
                self.notify_user_info(email,
                                      "job is pending availability of the build.")
            except sqlite3.OperationalError:
                self.notify_admin_exception("Error updating job")
                self.notify_user_exception(email,
                                           "job failed")
                self.purge_job(jobid)

    def check_running_jobs(self):
        """Check the running job if any.
        """
        try:
            self.cursor.execute("select * from jobs where status = 'running'")
            jobrows = self.cursor.fetchall()
        except sqlite3.OperationalError:
            self.notify_admin_exception("Error checking running jobs")
            raise

        if jobrows:
            ### We should never get here unless we crashed while processing
            ### a job. Lets just delete any jobs with 'running' status and
            ### notify the user.
            for jobrow in jobrows:
                # send email to user then delete job
                (jobid, email, build, label, runs, tcpdump, video, datazilla,
                 script, status, started, timestamp) = jobrow
                self.set_job(jobid, email, build, label, runs, tcpdump,
                             video, datazilla, script, status, started, timestamp)
                self.purge_job(jobid)

    def check_automatic_jobs(self):
        """If the current datetime is a calendar day later than the last
        time the automatic job was submitted and if the current hour
        is later than the automatic job's scheduled hour, submit the job."""
        now = datetime.datetime.now()
        for aj in self.automatic_jobs:
            aj_datetime = aj["datetime"]
            aj_hour = aj["hour"]
            if (now > aj_datetime and now.day != aj_datetime.day and
                now.hour >= aj_hour):
                self.create_job(aj["email"],
                                aj["build"],
                                aj["label"],
                                aj["runs"],
                                aj["tcpdump"],
                                aj["video"],
                                aj["datazilla"],
                                aj["script"],
                                aj["locations"],
                                aj["speeds"],
                                aj["urls"])
                aj["datetime"] = now

def main():

    parser = OptionParser()

    parser.add_option("--database",
                      action="store",
                      type="string",
                      dest="database",
                      default="jobmanager.sqlite",
                      help="Path to sqlite3 database file. "
                      "Defaults to jobmanager.sqlite in current directory.")

    parser.add_option("--log",
                      action="store",
                      type="string",
                      dest="log",
                      default="wptmonitor.log",
                      help="Path to log file. "
                      "Defaults to wptmonitor.log in current directory.")

    parser.add_option("--settings",
                      action="store",
                      type="string",
                      dest="settings",
                      default="settings.ini",
                      help="Path to configuration file. "
                      "Defauls to settings.ini in current directory.")

    parser.add_option("--pidfile",
                      action="store",
                      type="string",
                      default="/var/run/wptmonitor.pid",
                      help="File containing process id of wptcontroller "
                      "if --daemonize is specified.")

    parser.add_option("--daemonize",
                      action="store_true",
                      default=False,
                      help="Runs wptmonitor in daemon mode.")

    (options, args) = parser.parse_args()

    if not os.path.exists(options.settings):
        print "Settings file %s does not exist" % options.settings
        exit(2)

    jm = JobMonitor(options)

    try:
        while True:
            jm.check_automatic_jobs()
            jm.check_waiting_jobs()
            jm.check_running_jobs()
            jm.process_job()
            time.sleep(jm.sleep_time)
    except:
        jm.notify_admin_exception("Error in wptmonitor",
                                  "Terminating wptmonitor due to " +
                                  "unhandled exception: ")
        exit(2)

if __name__ == "__main__":
    main()

