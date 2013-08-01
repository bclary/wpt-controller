# wpt-controller

>Drive Web Page Test with arbitrary Firefox builds

## Test environment

The test environment uses the following machines:

wpt-server - An Ubuntu server running Webpagetest and wpt-controller.

wpr-server-record - An Ubuntu server running Web page replay under the
control of Webpagetest so that live web pages are recorded using web page
replay before being played back to the test clients with the specified
connectivity options.

wpr-server-replay - An Ubuntu server running Web page replay in replay
mode so that a fixed set of pages recorded in the http archive are replayed
back to the test clients with the specified connectivity options.

bc-winxp01 - A Windows XP test client running ipfw+dummynet, web page
replay and a patched version of Webpagetest's wptdriver. This client
is configured so that wptdriver will request web page replay record a
live site, then run tests on the recorded version of the page.

bc-win61i32-bld - A Windows 7 test client running ipfw+dummynet, web
page replay and a patched version of Webpagetest's wptdriver. This
client configured so that wtpdriver is unaware of web page replay and will
simply play back the previously recorded http archive for the requested
url.

## Setup

### Setup Webpagetest

Set up a WebPagetest server (e.g. wpt-server) and client machine locations according to
[WebPagetest's Private Instances](https://sites.google.com/a/webpagetest.org/docs/private-instances).
The following assumes webpagetest is to be installed on an Unbuntu machine into /var/www/webpagetest
and that the Apache web server runs under the www-data user and group.

#### Install pre-requisites
<pre>
sudo apt-get install apache2 ffmpeg php5 php5-gd php5-curl zlib1g zip curl
</pre>

#### Configure Apache
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

Edit /etc/apache2/sites-available/default Apache configuration as follows:

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

The most recent release of Webpagetest at this time is <a
href="https://github.com/WPO-Foundation/webpagetest/releases/tag/WebPagetest-2.12">WebPageTest-
2.12</a>.  Download and unpack the distribution, move www
subdirectory to <code>/var/www/webpagetest</code> and change the owner to
the Apache www-data user.

<pre>
mkdir -p ~/Downloads/webpagetest.org
cd ~/Downloads/webpagetest.org
curl -O https://github.com/WPO-Foundation/webpagetest/releases/download/WebPagetest-2.12/webpagetest_2.12.zip
unzip webpagetest_2.12.zip
sudo mv www /var/www/webpagetest
sudo chown -R www-data:www-data /var/www/webpagetest
cd /var/www/webpagetest
sudo chmod ug+w tmp results work/jobs work/video logs
</pre>

In addition to the other directories listed in setting up Private Instances,
make sure that the /var/www/webpagetest/installers/browsers/
directory is writable by the web server user.

<pre>
</pre>

* Edit /var/www/webpagetest/work/updates/wptupdate.ini and remove the
items from the version and md5 sections.

* Check out the source for wpt-controller onto the WebPagetest server
and make the directory writable by the web server user.

* Copy the wpt-controller settings.ini.example file to settings.ini and customize the
settings according to your needs:

* Optionally use a rewrite rule on the WebPagetest web server to map
http://wpt-server:port/wptcontroller.py to a more user friendly
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
* port - the port on which the wptcontroller.py script will listen.
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

sudo su www-data -c 'python wptcontroller.py'
sudo su www-data -c 'python  wptmonitor.py'
