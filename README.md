# wpt-controller

>Drive Web Page Test with arbitrary Firefox builds

## Test environment

This document describes a test environment consisting of the following
machines:

wpt-server - An Ubuntu server running WebPagetest and
wpt-controller. In our example, wpt-server is located at 192.168.1.29.

wpr-server-record - An Ubuntu server running Web page replay under the
control of WebPagetest so that live web pages are recorded using web
page replay before being played back to the test clients with the
specified connectivity options. In our example, wpr-server-record is
located at 192.168.1.34.

wpr-server-replay - An Ubuntu server running Web page replay in replay
mode so that a fixed set of pages recorded in the http archive are
replayed back to the test clients with the specified connectivity
options. In our example, wpr-server-replay is located at 192.168.1.35.

bc-winxp01 - A Windows XP test client running ipfw+dummynet, web page
replay and a patched version of WebPagetest's wptdriver. This client
is configured so that wptdriver will request web page replay record a
live site, then run tests on the recorded version of the page.

bc-win61i32-bld - A Windows 7 test client running ipfw+dummynet, web
page replay and a patched version of WebPagetest's wptdriver. This
client is configured so that wtpdriver is unaware of web page replay
and will simply play back the previously recorded http archive for the
requested url.

## Setup

### Setup WebPagetest server

Set up a WebPagetest server (e.g. wpt-server) and client machine
locations according to [WebPagetest's Private
Instances](https://sites.google.com/a/webpagetest.org/docs/private-instances).
The following assumes WebPagetest is to be installed on an Ubuntu
machine into /var/www/webpagetest and that the Apache web server runs
under the www-data user and group.

#### Install pre-requisites
<pre>
sudo apt-get install apache2 ffmpeg php5 php5-gd php5-curl zlib1g zip curl
# Note php5 may contain the required modules as compiled in modules which
# can be listed using <code>php5 -m</code>.
</pre>

#### Configure Apache

Edit /etc/apache2/apache2.conf and set the ServerName.

##### Enable Required Apache Modules
<pre>
cd /etc/apache2/mods-enabled
sudo ln -s ../mods-available/expires.load expires.load
sudo ln -s ../mods-available/headers.load headers.load
sudo ln -s ../mods-available/rewrite.load rewrite.load
# Use proxy to expose the wpt-controller web application running on
# localhost:8051 to external clients as http://wpt-server/wpt-controller
sudo ln -s ../mods-available/proxy.load proxy.load
sudo ln -s ../mods-available/proxy_http.load proxy_http.load
</pre>

Edit /etc/apache2/sites-available/default Apache configuration as
follows:

<pre>
--- default.orig        2013-05-10 12:19:48.493158939 -0700
+++ default        2013-05-17 14:07:51.701934938 -0700
@@ -1,16 +1,17 @@
 &lt;VirtualHost *:80&gt;
         ServerAdmin webmaster@localhost
 
-        DocumentRoot /var/www
+        DocumentRoot /var/www/webpagetest
         &lt;Directory /&gt;
                 Options FollowSymLinks
                 AllowOverride None
         &lt;/Directory&gt;
         &lt;Directory /var/www/&gt;
-                Options Indexes FollowSymLinks MultiViews
-                AllowOverride None
-                Order allow,deny
-                allow from all
+                Options Indexes FollowSymLinks
+                AllowOverride all
+                Order allow,deny
+                Allow from all
         &lt;/Directory&gt;
 
         ScriptAlias /cgi-bin/ /usr/lib/cgi-bin/
@@ -21,6 +22,16 @@
                Allow from all
        &lt;/Directory&gt;
 
+       ProxyRequests Off
+
+       &lt;Proxy *&gt;
+                Order deny,allow
+                Allow from all
+       &lt;/Proxy&gt;
+
+       ProxyPass /wpt-controller http://localhost:8051
+       ProxyPassReverse /wpt-controller http://localhost:8051
+
        ErrorLog ${APACHE_LOG_DIR}/error.log
 
        # Possible values include: debug, info, notice, warn, error, crit,
</pre>

so that it looks like

<pre>
&lt;VirtualHost *:80&gt;
        ServerAdmin webmaster@localhost

        DocumentRoot /var/www/webpagetest
        &lt;Directory /&gt;
                Options FollowSymLinks
                AllowOverride None
        &lt;/Directory&gt;
        &lt;Directory /var/www/&gt;
                Options Indexes FollowSymLinks
                AllowOverride all
                Order allow,deny
                Allow from all
        &lt;/Directory&gt;

        ScriptAlias /cgi-bin/ /usr/lib/cgi-bin/
        &lt;Directory "/usr/lib/cgi-bin"&gt;
                AllowOverride None
                Options +ExecCGI -MultiViews +SymLinksIfOwnerMatch
                Order allow,deny
                Allow from all
        &lt;/Directory&gt;

        ProxyRequests Off

        &lt;Proxy *&gt;
                Order deny,allow
                Allow from all
        &lt;/Proxy&gt;

        ProxyPass /wpt-controller http://localhost:8051
        ProxyPassReverse /wpt-controller http://localhost:8051

        ErrorLog ${APACHE_LOG_DIR}/error.log

        # Possible values include: debug, info, notice, warn, error, crit,
        # alert, emerg.
        LogLevel warn

        CustomLog ${APACHE_LOG_DIR}/access.log combined
&lt;/VirtualHost&gt;
</pre>

#### Install WebPagetest

The most recent release of WebPagetest at this time is <a
href="https://github.com/WPO-Foundation/webpagetest/releases/tag/WebPagetest-2.12">WebPageTest-
2.12</a>.  However the current version of wpt-controller relies up changes which have been
made to the json results format since WebPagetest 2.12 was released.
<del>Download and unpack the distribution</del>, <ins>Clone the repository</ins>, then
move the www subdirectory
to <code>/var/www/webpagetest</code> and change the owner to the
Apache www-data user.

<pre>
<del>
mkdir -p ~/Downloads/webpagetest.org
cd ~/Downloads/webpagetest.org
curl -O https://github.com/WPO-Foundation/webpagetest/releases/download/WebPagetest-2.12/webpagetest_2.12.zip
unzip webpagetest_2.12.zip
sudo mv webpagetest_2.12/www /var/www/webpagetest
</del>
<ins>
cd ~/Downloads/
git clone https://github.com/WPO-Foundation/webpagetest.git
sudo cp -a webpagetest/www /var/www/webpagetest
</ins>
sudo chown -R www-data:www-data /var/www/webpagetest
cd /var/www/webpagetest
sudo chmod -R ug+w tmp results work/jobs work/video logs
</pre>

#### Configure WebPagetest

WebPagetest can be configured through the .ini files located in
<code>/var/www/webpagetest/settings/</code>.

##### settings.ini

The settings.ini.sample file can be copied and customized to fit
your specific needs. The following example allows up to 100 runs
for each url.

<pre>
[settings]
product=WebPagetest
contact=bob@bclary.com
optLinks=0
maxruns=100
countTests=1
allowPrivate=0

; test options available
enableVideo=1
</pre>

##### connectivity.ini

The connectivity.ini file controls the "standard" bandwidth shaping
options available. Copy connectivity.ini.sample to connectivity.ini
and customize to your needs. The following adds Broadband (10
Mbps/10Mbps 90ms RTT), Modern Mobile (1 Mbps/1Mbps 150ms RTT), Classic
Mobile (400 Kbps/400 Kbps 300ms RTT) to the existing configurations.

<pre>
[Cable]
label="Cable (5/1 Mbps 28ms RTT)"
bwIn=5000000
bwOut=1000000
latency=28
plr=0

[DSL]
label="DSL (1.5 Mbps/384 Kbps 50ms RTT)"
bwIn=1500000
bwOut=384000
latency=50
plr=0

[FIOS]
label="FIOS (20/5 Mbps 4ms RTT)"
bwIn=20000000
bwOut=5000000
latency=4
plr=0

[Dial]
label="56K Dial-Up (49/30 Kbps 120ms RTT)"
bwIn=49000
bwOut=30000
latency=120
plr=0

[3G]
label="Mobile 3G (1.6 Mbps/768 Kbps 300ms RTT)"
bwIn=1600000
bwOut=768000
latency=300
plr=0

[Native]
label="Native Connection (No Traffic Shaping)"
bwIn=0
bwOut=0
latency=0
plr=0

[Broadband]
label="Broadband (10 Mbps/10Mbps 90ms RTT)"
bwIn=10000000
bwOut=10000000
latency=90
plr=0

[ModernMobile]
label="Modern Mobile (1 Mbps/1Mbps 150ms RTT)"
bwIn=1000000
bwOut=1000000
latency=150
plr=0

[ClassicMobile]
label="Classic Mobile (400 Kbps/400 Kbps 300ms RTT)"
bwIn=400000
bwOut=400000
latency=300
plr=0
</pre>

##### locations.ini

locations.ini defines the different machine and browser combinations
available to the private WebPagetest instance. These settings
including the key values must match those set up on the client test
machine's wptdriver.ini or urlBlast.ini. In the example below, we
define two machines: bc-winxp01 and bc-win61i32-bld which each have
Firefox and Chrome configured to run tests.

<pre>
;
; [locations] contains a list of "locations" which will be displayed
; in WebPagetest's location select input. These really correspond more
; to machine names rather than a physical location.
[locations]
1=bc-winxp01
2=bc-win61i32-bld
default=bc-winxp01

;
; For each machine name listed in [locations], create a section
; which specifies the browser configuration sections for that
; location. In this example we use wptdriver configurations which
; are signified by the "w" suffix on the machine/location name.
;
[bc-winxp01]
1=bc-winxp01w
label=bc-winxp01

[bc-win61i32-bld]
1=bc-win61i32-bldw
label=bc-win61i32-bld

;
; For each browser configuration section named above, create
; a section which defines the supported browser.
;
[bc-winxp01w]
browser=Chrome,Firefox
label="bc-winxp01w"
key=XXXXXX

[bc-win61i32-bldw]
browser=Chrome,Firefox
label="bc-win61i32-bldw"
key=XXXXXX
</pre>

##### .htaccess

Edit /var/www/webpagetest/.htaccess and add the following rewrite rule:

<pre>
RewriteRule ^jsonResult/([a-zA-Z0-9_]+)/$ /jsonResult.php?test=$1 [qsa]
</pre>

You can copy and edit the line for xmlResult.


#### Configuring Webpagetest to support wpt-controller

In addition to the other directories listed in setting up Private Instances,
make sure that the <code>/var/www/webpagetest/installers/browsers/</code>
directory is writable by the web server user. This is needed by wpt-controller
so that it can update the firefox.dat and download the requested firefox build.

<pre>
sudo chmod -R ug+w /var/www/webpagetest/installers/browsers
</pre>

Edit <code>/var/www/webpagetest/work/updates/wptupdate.ini</code> and
remove the items from the version and md5 sections. This prevents the
wptdriver software on the clients from updating wptdriver.exe and
related software.  This is necessary for the time being since we need
to run a patched version of wptdriver.exe on the clients in order to
support updating Firefox on demand.

### Setup wpt-controller

Check out the source for wpt-controller onto the WebPagetest server
and make the directory writable by the web server user. You may need
to first install git via <code>sudo git apt-get install git</code>.

<pre>
cd /var/www
sudo git clone https://github.com/bclary/wpt-controller
sudo chown www-data:www-data wpt-controller
</pre>

#### Install 7z

<code>wptmonitor.py</code> uses 7z to unpack Firefox installers.

<pre>
sudo apt-get install p7zip-full
</pre>

#### Install BeautifulSoup

<code>wptmonitor.py</code> uses BeautifulSoup to scrape urls for build urls.

<pre>
sudo apt-get install python-pip
sudo pip install BeautifulSoup
</pre>

#### Install Datazilla

<code>wptmonitor.py</code> uses Datazilla's dzclient to submit results to datazilla.mozilla.org.

<pre>
sudo pip install datazilla
</pre>

#### wpt-controller Configuration

The wpt-controller is configured via the settings.ini file. It
consists of 4 required sections: server, mail, admin, defaults and
optional sections for automatically submitted jobs.  Copy the
wpt-controller settings.ini.example file to settings.ini and customize
the settings according to your needs:

##### server

* server - the external address or dns name of the wpt-server.
* port - the port on which the wptcontroller.py script will listen.
* sleep_time - time in seconds to wait after finishing a job before polling for the next job.
* check_minutes - internval in minutes to check builds for availability.
* api_key - the WebPagetest api key.
* firefoxpath - the path where to download Firefox installers. This will typically <code>/var/www/webpagetest/installers/browsers</code>.
* firefoxdatpath - the path to the firefox.dat file. This will typically <code>/var/www/webpagetest/installers/browsers</code>.

##### mail
* username - email user account
* password = email user password
* mailhost = mail host name

##### admin

* admin_toaddrs - comma delimited list of administrator email
addresses to be sent error messages.
* admin_subject - email subject for administrator email messages.
* admin_loglevel - default loglevel for file based logs.

##### automatic (optional)

* jobs - comma delimited list of automatic job names which will be
submitted daily. These job names are also the names of additional
sections in the ini file which describe the job to be submitted.

##### <job name> (optional, but required if listed in automatic section)

* email - email address of person to receive user notification emails regarding the job.
* label - label to be used for the job.
* build - url for the build or build directory where the build can be downloaded.
* urls - comma delimited list of urls to be tested in the job.
* prescript - string containing a WebPagetest script to be executed prior to the url loads.
prescript can be used to set preferences prior to starting a test. prescript will be used for
every url in the urls list.
* scripts - comma delimited list of file names containing scripts to be executed after url loads.
Each script file corresponds to the url in the same position in the urls list.
* locations - comma delimited list of locations to be tested in the job. Note these locations
consist of the <machine-name>:<browser>, e.g. bc-win61i32-bldw:Firefox.
* speeds - comma delimited list of speeds to be tested.
* runs - integer number of runs each url should be tested.
* tcpdump - on to collect a tcpdump of the test.
* video - on to collect a video of the test.
* datazilla - on to submit the results to datazilla.
* hour - hour of the day to submit the job.

##### defaults

* locations - comma delimited list of WebPagetest location:Browsers
* urls - comma delimited list of urls

#### Running wpt-controller manually

In order to run wpt-controller manually, run the following commands as the web user:

<pre>
sudo su www-data -c 'python wptcontroller.py'
</pre>

<pre>
sudo su www-data -c 'python wptmonitor.py'
</pre>

#### Installing and running wpt-controller as a service.

To set up wptcontroller.py and wptmonitor.py as services which
automatically start at boot time, first create log directories which
are writable by the www-data user:

<pre>
sudo mkdir /var/log/{wptcontroller,wptmonitor}
sudo chown root:www-data /var/log/{wptcontroller,wptmonitor}
sudo chmod ug+w /var/log/{wptcontroller,wptmonitor}
</pre>

Then copy the wptcontroller, wptmonitor initd scripts into /etc/init.d/

<pre>
sudo cp /var/www/wpt-controller/init.d/wptcontroller /etc/init.d/
sudo cp /var/www/wpt-controller/init.d/wptmonitor /etc/init.d/
</pre>

and then setup and enable the services

<pre>
sudo update-rc.d wptcontroller defaults
sudo update-rc.d wptcontroller enable

sudo update-rc.d wptmonitor defaults
sudo update-rc.d wptmonitor enable
</pre>

You can start, stop, get status for the services using the
<code>service</code> command. For example:

<pre>
sudo service wptcontroller status
sudo service wptcontroller start
sudo service wptcontroller stop
</pre>

### Setup Web Page relay servers

The test environment described here uses [Web Page
Replay](http://code.google.com/p/web-page-replay/) on two Ubuntu servers,
wpr-server-record and wpr-server-replay, to provide the ability to
record and replay web pages from stored archives.

For each server, download web-page-replay and wpt-controller and set
up a service webpagereplay to automatically start web-page-replay on
boot:

<pre>
sudo apt-get install git subversion
sudo mkdir -p /mozilla/projects
# Replace <i>user</i> with your userid
sudo chown -R <i>user</i>:<i>user</i> /mozilla
cd /mozilla/projects
svn checkout http://web-page-replay.googlecode.com/svn/trunk/ web-page-replay
git clone https://github.com/bclary/wpt-controller
sudo cp wpt-controller/init.d/webpagereplay /etc/init.d/
sudo mkdir /var/log/webpagereplay
sudo update-rc.d webpagereplay defaults
sudo update-rc.d webpagereplay enable
</pre>

Before we start the webpagereplay service on either machine, we must first
create an initial empty archive.

<pre>
cd /mozilla/projects/web-page-replay
sudo ./replay.py --record ./archive.wpr
# Press Control-C to terminate replay.py
</pre>

The wpr-server-record server will be controlled by the WebPagetest
client's to turn on Web Page Replay's recording and replay modes.

The wpr-server-replay server will always run in replay mode. Once we
have set up the WebPagetest clients, we will temporarily run the web replay
server in record mode to create the archive. It is also possible to
create archives for additional urls and add them to the replay archive
using the httparchive.py utility in Web Page replay.

### Setup WebPagetest clients

#### Create Firefox installation directory

On each client machines, create the directory C:\firefox-webpagetest\ and make
sure that the Administrative user can write to the directory and execute programs
located there. WebPagetest will install the test versions of Firefox to this
directory.

#### Configure Web Page Replay on the client machines

In order to route all requests from the client machine through the
appropriate Web Page Replay server, we can set the DNS server to point
to the appropriate Web Page Replay server. We can either do this by
default or we can run the Web Page Replay script replay.py on the
client machines to temporarily change the DNS server to point to the
appropriate Web Page Replay server.

##### bc-winxp01 DNS

bc-winxp01 uses WebPagetest and Web Page Replay to record live web
pages, then replays the recorded web page. You can manually set the
DNS to point to the wpr-server-record (192.168.1.34) to automatically
route all requests through the wpr-server-record server.

If you wish to use Web Page Replay to modify the DNS, install Web Page Replay in
c:\web-page-replay either by downloading a release or checking out the
source from
[http://code.google.com/p/web-page-replay/](http://code.google.com/p/web-page-replay/). You
will need to install the Windows version of Python which can be
downloaded from
[http://www.python.org/downloads/](http://www.python.org/downloads/). Assuming
you have installed Python into C:\Python27, create a batch file
replay.bat in c:\web-page-replay containing

<pre>
cd c:\web-page-replay
c:\Python27\python replay.py --server 192.168.1.34
</pre>

and place a shortcut to the batch file in your startup folder.

##### bc-win61i32-bld DNS

bc-win61i32-bld uses WebPagetest and Web Page Replay to replay previously
recorded web pages. You can manually set the DNS to point to the
wpr-server-replay (192.168.1.35) to automatically route all requests
through the wpr-server-replay server.

If you wish to use Web Page Replay to modify the DNS, install Web Page Replay in
c:\web-page-replay either by downloading a release or checking out the
source from
[http://code.google.com/p/web-page-replay/](http://code.google.com/p/web-page-replay/). You
will need to install the Windows version of Python which can be
downloaded from
[http://www.python.org/downloads/](http://www.python.org/downloads/). Assuming
you have installed Python into C:\Python27, create a batch file
replay.bat in c:\web-page-replay containing

<pre>
cd c:\web-page-replay
c:\Python27\python replay.py --server 192.168.1.35
</pre>

and place a shortcut to the batch file in your startup folder.

#### Install WebPagetest onto the client machines

Install WebPagetest onto each client machine according to the instructions in
[https://sites.google.com/a/webpagetest.org/docs/private-instances#TOC-General-Machine-Configuration-common-for-all-browsers-](WebPagetest's instructions).

Be sure to place shortcuts to WebPagetest's ipfw.cmd and wptdriver.exe in your
startup folder.

##### bc-winxp01 wptdriver.ini (WebPagetest and Web Page Record/Replay)

Edit the wptdriver.ini for bc-winxp01 to match the location specified
on the WebPagetest server. Note that we specify the url to the
WebPagetest server and the Web Page Replay host using IP addresses
since we will be modifying the DNS entry to point to the Web Page
Replay server and will not be able to resolve their host names. In our
example, the WebPagetest server wpt-server is located at 192.168.1.29 and the
recording Web Page Replay server wpr-server-record is located at 192.168.1.34.

<pre>
[WebPagetest]
url=http://192.168.1.29/
web_page_replay_host=192.168.1.34
location=bc-winxp01w
browser=chrome
Time Limit=300
key=XXXXXX
; software_update_interval_minutes is the new setting available in our
; patched version of wptdriver. This forces the client to always check
; for an updated Firefox build prior to running a test.
software_update_interval_minutes=0

[chrome]
exe="C:\Program Files\Google\Chrome\Application\chrome.exe"
options='--load-extension="%WPTDIR%\extension" --user-data-dir="%PROFILE%" --no-proxy-server'
installer=http://www.webpagetest.org/installers/browsers/chrome.dat

[Firefox]
exe="C:\firefox-webpagetest\firefox.exe"
options='-profile "%PROFILE%" -no-remote'
; Tell wptdriver to check the wpt-server for Firefox updates.
installer=http://192.168.1.29/installers/browsers/firefox.dat
template=firefox
</pre>

##### bc-win61i32-bld wptdriver.ini (WebPagetest and Web Page Replay)

Edit the wptdriver.ini for bc-win61i32-bld to match the location
specified on the WebPagetest server. Note that we specify the url to
the WebPagetest server using IP address since we will be modifying the
DNS entry to point to the Web Page Replay server and will not be able
to resolve their host names. In our example, the WebPagetest server
wpt-server is located at 192.168.1.29.

Note that in this replay-only client, we do not tell WebPagetest about
the Web Page Replay server. This will prevent WebPagetest from attempting
to record each test url prior to testing it.

<pre>
[WebPagetest]
url=http://192.168.1.29/
location=bc-win61i32-bldw
browser=chrome
Time Limit=300
key=XXXXXX
; software_update_interval_minutes is the new setting available in our
; patched version of wptdriver. This forces the client to always check
; for an updated Firefox build prior to running a test.
software_update_interval_minutes=0

[chrome]
exe="C:\Program Files\Google\Chrome\Application\chrome.exe"
options='--load-extension="%WPTDIR%\extension" --user-data-dir="%PROFILE%" --no-proxy-server'
installer=http://www.webpagetest.org/installers/browsers/chrome.dat

[Firefox]
exe="C:\firefox-webpagetest\firefox.exe"
options='-profile "%PROFILE%" -no-remote'
; Tell wptdriver to check the wpt-server for Firefox updates.
installer=http://192.168.1.29/installers/browsers/firefox.dat
template=firefox
</pre>

#### Build custom version of wptdriver

We use a custom build of the wptdriver software from WebPagetest in
order to force the client to check for a new build prior to running
each test. This allows us to submit a job to the wptcontroller web
application consisting of a test for a specific build of Firefox for a
location, speed and url, have the wptmonitor service download the build
and submit the test when the build is ready.

You will need Visual Studio 2010 SP1 to build the WebPagetest
software. For more information see
[https://github.com/WPO-Foundation/webpagetest](https://github.com/WPO-Foundation/webpagetest)

Download the source for Webpagetest from either
[https://github.com/WPO-Foundation/webpagetest/releases/tag/WebPagetest-2.12](https://github.com/WPO-Foundation/webpagetest/releases/tag/WebPagetest-2.12)
or
[https://github.com/WPO-Foundation/webpagetest](https://github.com/WPO-Foundation/webpagetest)
and apply the patch in webpagetest-software-update.patch. Create a
custom build of wptdriver and deploy the following files to the
WebPagetest directory on each client machine:

<pre>
wptdriver.exe
wptupdate.exe
wptwatchdog.exe
wptbho.dll
wptglobal.dll
wpthook.dll
</pre>

