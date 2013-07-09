# wpt-controller

>Drive Web Page Test with arbitrary Firefox builds

## Setup

* Set up a WebPagetest server (e.g. wpt-server) and client machine locations according to
[WebPagetest's Private Instances](https://sites.google.com/a/webpagetest.org/docs/private-instances).

* Make sure that the /var/www/webpagetest/installers/browsers/
directory is writable by the web server user.

* Edit /var/www/webpagetest/work/updates/wptupdate.ini and remove the
items from the version and md5 sections.

* Check out the source for wpt-controller onto the WebPagetest server
and make the directory writable by the web server user.

* Copy the wpt-controller settings.ini.example file to settings.ini and customize the
settings according to your needs:

* Optionally use a rewrite rule on the WebPagetest web server to map
http://wpt-server:port/accept_jobs.wsgi to a more user friendly
location such as
[http://wpt-server/controller](http://wpt-server/controller).

* Download the source for Webpagetest from
[https://code.google.com/p/webpagetest/source/checkout](https://code.google.com/p/webpagetest/source/checkout)
and apply the patch in webpagetest-software-update.patch. Create a
custom build of wptdriver and deploy to the WebPagetest client machine
locations.

* On the client machine locations, edit the wptdriver.ini settings file:
** add software_update_interval_minutes=0 to the WebPagetest section.
** edit the Firefox section of the
wptdriver.ini file and change the installer to point to
[http://wpt-server/installers/browsers/firefox.dat](http://wpt-server/installers/browsers/firefox.dat).

## Configuration

The wpt-controller is configured via the settings.ini file. It consists of 4 sections:

### server

* server - the external address or dns name of the wpt-server.
* port - the port on which the accept_jobs.wsgi script will listen.
* sleep_time - time in seconds to wait after finishing a job before polling for the next job.
* check_minutes - internval in minutes to check builds for availability.
* api_key - the WebPagetest api key.
* firefoxpath - the path where to download Firefox installers.
* firefoxdatpath - the path to the firefox.dat file.

### mail
* username - email user account
* password = email user password
* mailhost = mail host name

### admin

* admin_toaddrs - comma delimited list of administrator email
addresses to be sent error messages.
* admin_subject - email subject for administrator email messages.
* admin_loglevel - default loglevel for file based logs.

### defaults

* locations - comma delimited list of WebPagetest location:Browsers
* urls - comma delimited list of urls

## Running

sudo su www-data -c 'python accept_jobs.wsgi'
sudo su www-data -c 'python  monitor_jobs.py'
