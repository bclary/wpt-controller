#!/usr/bin/env python
# This Source Code is subject to the terms of the Mozilla Public License
# version 2.0 (the "License"). You can obtain a copy of the License at
# http://mozilla.org/MPL/2.0/.

# modified from http://webpython.codepoint.net/wsgi_request_parsing_post
# to save submitted jobs.

# from autophone's jobs.py
import ConfigParser
import logging
import sqlite3
import os
import json
import datetime

from wsgiref.simple_server import make_server
from cgi import parse_qs, escape

from logging.handlers import TimedRotatingFileHandler
from emailhandler import SMTPHandler

def application(environ, start_response):
    email = ''
    build = ''
    label = ''
    runs = ''
    locations = []
    speeds = []
    urls = []

    if 'REQUEST_METHOD' in environ and environ['REQUEST_METHOD'] == 'GET':
        pass
    elif 'REQUEST_METHOD' in environ and environ['REQUEST_METHOD'] == 'POST':
        # the environment variable CONTENT_LENGTH may be empty or missing
        try:
            request_body_size = int(environ.get('CONTENT_LENGTH', 0))
        except (ValueError):
            request_body_size = 0

        # When the method is POST the query string will be sent
        # in the HTTP request body which is passed by the WSGI server
        # in the file like wsgi.input environment variable.
        request_body = environ['wsgi.input'].read(request_body_size)
        try:
            d = json.loads(request_body)
            email = d.get('email', [''])[0]
            build = d.get('build', [''])[0]
            label = d.get('label', [''])[0]
            runs = d.get('runs', [''])[0]
        except:
            d = parse_qs(request_body)
            email = d.get('email', [''])[0]
            build = d.get('build', [''])[0]
            label = d.get('label', [''])[0]
            runs = d.get('runs', [''])[0]

        locations = d.get('locations', [])
        speeds = d.get('speeds', [])
        urls = d.get('urls', [])

        # Always escape user input to avoid script injection
        email = escape(email.strip())
        build = escape(build.strip())
        label = escape(label.strip())
        runs = escape(runs.strip())
        locations = [escape(location.strip()) for location in locations]
        speeds = [escape(speed.strip()) for speed in speeds]
        urls = [escape(url.strip()) for url in urls]

        try:
            cursor.execute(
                'insert into jobs(email, build, label, runs, status, started) '
                'values (?, ?, ?, ?, ?, ?)',
                (email, build, label, runs, 'waiting',
                 datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')))
            connection.commit()
            jobid = cursor.lastrowid
        except sqlite3.OperationalError:
            msg = 'SQLError inserting job: email: %s, build: %s, label: %s, runs: %s' % (email, build, label, runs)
            emaillogger.exception(msg)
            notify_user(email, 'Your webpagetest job failed').exception(msg)
            raise

        for location in locations:
            try:
                cursor.execute(
                    'insert into locations(location, jobid) '
                    'values (?, ?)',
                    (location, jobid))
                connection.commit()
            except sqlite3.OperationalError:
                msg = 'SQLError inserting location: email: %s, build: %s, label: %s, location: %s' % (email, build, label, location)
                emaillogger.exception(msg)
                notify_user(email, 'Your webpagetest job failed').exception(msg)
                raise

        for speed in speeds:
            try:
                cursor.execute(
                    'insert into speeds(speed, jobid) values (?, ?)',
                    (speed, jobid))
                connection.commit()
            except sqlite3.OperationalError:
                msg = 'SQLError inserting speed: email: %s, build: %s, label: %s, location: %s' % (email, build, label, speed)
                emaillogger.exception(msg)
                notify_user(email, 'Your webpagetest job failed').exception(msg)
                raise

        for url in urls:
            try:
                cursor.execute(
                    'insert into urls(url, jobid) values (?, ?)',
                    (url, jobid))
                connection.commit()
            except sqlite3.OperationalError:
                msg = 'SQLError inserting url: email: %s, build: %s, label: %s, url: %s' % (email, build, label, url)
                emaillogger.exception(msg)
                notify_user(email, 'Your webpagetest job failed').exception(msg)
                raise

    else:
        # error?
        pass

    currentteststable = ''

    try:
        cursor.execute('select * from jobs')
        jobrows = cursor.fetchall()
    except sqlite3.OperationalError:
        emaillogger.exception('SQLError selecting jobs.')
        raise

    if jobrows:
        currentteststable = '<table>'

    for jobrow in jobrows:
        jobid = jobrow[0]
        try:
            cursor.execute(
                'select * from locations where jobid=:jobid',
                {'jobid': jobid})
            locationrows = cursor.fetchall()
        except sqlite3.OperationalError:
            emaillogger.exception('SQLError selecting locations for job %s.' % jobid)
            raise

        try:
            cursor.execute(
                'select * from speeds where jobid=:jobid',
                {'jobid': jobid})
            speedrows = cursor.fetchall()
        except sqlite3.OperationalError:
            emaillogger.exception('SQLError selecting speeds for job %s.' % jobid)
            raise

        try:
            cursor.execute(
                'select * from urls where jobid=:jobid',
                {'jobid': jobid})
            urlrows = cursor.fetchall()
        except sqlite3.OperationalError:
            emaillogger.exception('SQLError selecting urls for job %s.' % jobid)
            raise

        currentteststable += (
            '<tr>' +
            '<th>jobs id</th><th>jobs email</th><th>jobs build</th><th>jobs label</th><th>jobs runs</th><th>jobs status</th><th>jobs started</th><th>jobs timestamp</th>' +
            '<th>locations id</th><th>locations location</th><th>locations jobid</th>' +
            '<th>speeds id</th><th>speeds speed</th><th>speeds job id</th>' +
            '<th>urls id</th><th>urls url</th><th>urls jobid</th>' +
            '</tr>')

        for locationrow in locationrows:
            for speedrow in speedrows:
                for urlrow in urlrows:
                    args = []
                    args.extend(jobrow)
                    args.extend(locationrow)
                    args.extend(speedrow)
                    args.extend(urlrow)

                    currentteststable += (
                        ('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>' +
                        '<td>%s</td><td>%s</td><td>%s</td> <td>%s</td><td>%s</td><td>%s</td>' +
                        '<td>%s</td><td>%s</td><td>%s</td>') % tuple(args))

    if jobrows:
        currentteststable += '</table>'

    response_body = html % (email or 'Empty',
                            build or 'Empty',
                            label or 'Empty',
                            runs or 'Empty',
                            ', '.join(locations or ['No Locations']),
                            ', '.join(speeds or ['No Speeds']),
                            '\n'.join(urls or ['No urls']),
                            currentteststable)
    status = '200 OK'
    response_headers = [('Content-Type', 'text/html'),
                        ('Content-Length', str(len(response_body)))]
    start_response(status, response_headers)
    return [str(response_body)]


def notify_user(user, subject):
    """Set the useremail handler's to address and subject fields
    and return a reference to the userlogger object."""
    userhandler.toaddrs = [user]
    userhandler.subject = subject
    return userlogger


if __name__ == '__main__':

    from optparse import OptionParser

    parser = OptionParser()

    parser.add_option('--database', action='store', type='string', dest='database',
                      default='jobmanager.sqlite', help='Path to sqlite3 database file. '
                      'Defaults to jobmanager.sqlite in current directory.')

    parser.add_option('--log', action='store', type='string', dest='log',
                      default='accept.log', help='Path to accepter log file. '
                      'Defaults to accept.log in current directory.')

    parser.add_option('--settings', action='store', type='string', dest='settings',
                      default='settings.ini', help='Path to configuration file. '
                      'Defauls to settings.ini in current directory.')

    (options, args) = parser.parse_args()

    config = ConfigParser.RawConfigParser()
    config.readfp(open(options.settings))
    server = config.get('server', 'server')
    try:
        port = config.getint('server', 'port')
    except ConfigParser.Error:
        port = 8051

    default_locations = config.get('defaults', 'locations').split(',')
    default_urls = config.get('defaults', 'urls').split(',')

    mail_username = config.get('mail', 'username')
    mail_password = config.get('mail', 'password')
    mail_host = config.get('mail', 'mailhost')

    admin_toaddrs = config.get('admin', 'admin_toaddrs').split(',')
    admin_subject = config.get('admin', 'admin_subject')

    admin_loglevel = logging.DEBUG
    try:
        admin_loglevel = getattr(logging,
                                 config.get('admin',
                                            'admin_loglevel'))
    except AttributeError:
        pass
    except ConfigParser.Error:
        pass

    logger = logging.getLogger()
    logger.setLevel(admin_loglevel)
    filehandler = TimedRotatingFileHandler(options.log,
                                           when='D',
                                           interval=1,
                                           backupCount=7,
                                           encoding=None,
                                           delay=False,
                                           utc=False)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    filehandler.setFormatter(formatter)
    logger.addHandler(filehandler)

    # Set up the administrative logger with an SMPT handler. It
    # should also bubble up to the root logger so we only need to
    # use it for ERROR or CRITICAL messages.

    emaillogger = logging.getLogger('email')
    emaillogger.setLevel(logging.ERROR)
    emailhandler = SMTPHandler(mail_host,
                               mail_username,
                               admin_toaddrs,
                               admin_subject,
                               credentials=(mail_username,
                                            mail_password),
                               secure=())
    emaillogger.addHandler(emailhandler)

    userlogger = logging.getLogger('user')
    userlogger.propagate = False
    userlogger.setLevel(logging.INFO)
    userhandler = SMTPHandler(mail_host,
                              mail_username,
                              admin_toaddrs,
                              'user subject',
                              credentials=(mail_username,
                                           mail_password),
                              secure=())
    userlogger.addHandler(userhandler)

    if os.path.exists(options.database):
        try:
            connection = sqlite3.connect(options.database)
            connection.execute('PRAGMA foreign_keys = ON;')
            cursor = connection.cursor()
        except sqlite3.OperationalError:
            emaillogger.exception('SQLError creating connection to database %s' % options.database)
            raise
    else:
        try:
            connection = sqlite3.connect(options.database)
            connection.execute('PRAGMA foreign_keys = ON;')
            cursor = connection.cursor()
            cursor.execute('create table jobs ('
                           'id integer primary key autoincrement, '
                           'email text, '
                           'build text, '
                           'label text, '
                           'runs text, '
                           'status text, '
                           'started text, '
                           'timestamp text'
                           ')'
            )
            connection.commit()
            cursor.execute('create table locations ('
                           'id integer primary key autoincrement, '
                           'location text, '
                           'jobid references jobs(id)'
                           ')'
            )
            connection.commit()
            cursor.execute('create table speeds ('
                           'id integer primary key autoincrement, '
                           'speed text, '
                           'jobid references jobs(id)'
                           ')'
            )
            connection.commit()
            cursor.execute('create table urls ('
                           'id integer primary key autoincrement, '
                           'url text, '
                           'jobid references jobs(id)'
                           ')'
            )
            connection.commit()
        except sqlite3.OperationalError:
            emaillogger.exception('SQLError creating schema in database %s' % options.database)
            raise

    html = """
    <html>
    <body>
       <form method="post" action="accept_jobs.wsgi">
          <p>
             <label>Email: <input type="text" name="email" maxlength="2048"></label>
          </p>
          <p>
             <label>Build: <input type="text" name="build"></label>
          </p>
          <p>
             <label>Label: <input type="text" name="label"></label>
          </p>
          <p>
            <label>Runs: <input type="text" name="runs" value="1"></label>
          <p>
            <!--
              These are the predefined connection speeds.
              We could also allow custom speeds with:
              bandwidth_up, bandwidth_down, latency, packet_loss_rate.
            -->
            <label>Speeds:
            <select name="speeds" multiple>
               <option>Native</option>
               <option>Cable</option>
               <option>DSL</option>
               <option>Fios</option>
               <option>Dial</option>
            </select>
            </label>
          </p>
          <p>
             <label>URLS:
             <select name="urls" multiple>"""
    html += ''.join(['<option>' + url + '</option>' for url in default_urls])
    html += """</select>
             <label>
          </p>
          <p>
            <label>Locations:
            <select name="locations" multiple>"""
    html += ''.join(['<option>' + location + '</option>' for location in default_locations])
    html += """</select>
            </label>
          <p>
             <input type="submit" value="Submit">
          </p>
       </form>
       <p>
          Email: %s<br>
          Build: %s<br>
          Label: %s<br>
          Runs: %s<br>
          Locations: %s<br>
          Speeds: %s<br>
          URLS: %s<br>
       </p>
       <p>Current Tests</p>
       %s
    </body>
    </html>
    """

    httpd = make_server(server, port, application)
    httpd.serve_forever()

