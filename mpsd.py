#!/usr/bin/env python

import sys
import time
import mpd
import os
import logging
import logging.handlers
from sqlite3 import Error as SqlError
from socket import error as SocketError
from socket import timeout as SocketTimeout

import dbase
import daemon

#-------------------------------------------
# Change the following to suit your system
#

# MPD Info
HOST = 'localhost'
PORT = '6600'
#If no password, set to None
PASSWORD = None

DB_PATH = "/var/local/mpsd.db"
LOG_FILE = "/var/log/mpd/mpsd.log"
PID_FILE = "/tmp/mpsd.pid"

# How often to poll MPD (in seconds)
# The lower the poll frequency, the more accurate listening time
# will be, but will use more resources.
POLL_FREQUENCY = 1

# How far into the song to add it as a fraction of the songlength
# Make sure < 1, and remember that poll frequency may cause innaccuracies
# as well, if threshold is high.
# to add at beginning of a song, set to 0
ADD_THRESHOLD = 0.2

# The default stats template
STATS_TEMPLATE = "/home/marc/projects/mpsd/template.html"
# Path to stats generation script, default "sqltd"
STATS_SCRIPT = "sqltd"

#
# Configuration ends here
#-------------------------------------------

log = logging.getLogger('mpsd')
LOG_LEVEL = logging.INFO
LOG_FORMAT = '%(levelname)s\t%(asctime)s\t%(module)s %(lineno)d\t%(message)s'
STDOUT_FORMAT = '%(levelname)s\t%(module)s\t%(message)s'

def usage():
    print "Usage:"
    print "  %s [OPTIONS] (start|stop|restart|stats)\n" % sys.argv[0]
    print "Music Player Stats Daemon - a daemon for recording stats from MPD"

    print "\nRequired Arguments:"
    print "  One of (start|stop|restart|stats):"
    print "    start\n\tStart mpsd"
    print "    stop\n\tStop the currently running mpsd instance"
    print "    restart\n\tRestart the currently running mpsd instance"
    print "    stats [stats_template]"
    print "    \tGenerate statistics using the specified template file."

    print "\nOptional Arguments:"
    print "  -c, --config <FILE>\n\tSpecify the config file (not implemented)"
    print "  -d, --debug\n\tSet logging mode to debug"
    print "  --fg\n\tRun mpsd in the foreground"
    print "  --template TEMPLATE_FILE\n\tThe template file to use when ",
    print "generating statistics."
    print "  -h, --help\n\tShow this help message"

def initialize_logger(logfile, log_level=logging.INFO, stdout=False):
    fhandler = logging.handlers.RotatingFileHandler(filename=logfile,
                        maxBytes=50000, backupCount=5)
    fhandler.setFormatter(logging.Formatter(LOG_FORMAT))
    log.setLevel(log_level)
    log.addHandler(fhandler)

    if stdout:
        shandler = logging.StreamHandler()
        shandler.setFormatter(logging.Formatter(STDOUT_FORMAT))
        log.addHandler(shandler)

class MPD(object):
    def __init__(self, host=None, port=None, password=None):
        self.host = host
        self.port = port
        self.password = password
        self.client = mpd.MPDClient()

    def connect(self):
        """
        Connect to an mpd server
        """
        try:
            self.client.connect(host=self.host, port=self.port)
        except (mpd.MPDError, SocketError):
            log.debug("Could not connect to %s:%s" % (self.host, self.port))
            return False
        except:
            log.error("Unexpected error: %s" % (sys.exc_info()[1]))
            return False
        else:
            log.info("Connected to %s:%s" % (self.host, self.port))
            return True
        return self.authenticate() if self.password else True

    def authenticate(self):
        """
        Authenticate mpd connection
        """
        try:
            self.client.password(self.password)
        except mpd.CommandError:
            log.error("Could not authenticate")
            return False
        except mpd.ConnectionError:
            log.error("Problems authenticating.")
            return False
        except:
            log.error("Unexpected error: %s", sys.exc_info()[1])
            return False
        else:
            log.info("Authenticated")
            return True

    def getCurrentSong(self):
        """
        Get the current song from the mpd server
        """
        try:
            curSong = self.client.currentsong()
            for k in curSong.keys():
                if isinstance(curSong[k], (tuple, list)):
                    curSong[k] = curSong[k][0]
                curSong[k] = unicode(curSong[k], 'utf-8')
            return curSong
        except (mpd.MPDError, SocketTimeout):
            log.error("Could not get status: %s" % (sys.exc_info()[1]))
            return {}

    def getStatus(self):
        """
        Get the status of the mpd server
        """
        try:
            return self.client.status()
        except mpd.CommandError:
            log.error("Could not get status")
            return False
        except mpd.ConnectionError:
            log.error("Error communicating with client.")
            return False
        except:
            log.error("Unexpected error:", sys.exc_info()[1])
            return False
        else:
            return True

    def disconnect(self):
        """
        Disconect from the mpd server
        """
        self.client.disconnect()

class mpdStatsDaemon(daemon.Daemon):
    def __init__(self, template=STATS_TEMPLATE, fork=True,
            log_level=logging.INFO,
            stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
        # daemon settings
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.pidfile = PID_FILE
        self.fork = fork

        # config options
        self.log_file = LOG_FILE
        self.poll_frequency = POLL_FREQUENCY
        self.add_threshold = ADD_THRESHOLD
        self.stats_script = STATS_SCRIPT
        self.template = template

        self.mpd = MPD(HOST, PORT, PASSWORD)
        print "create db object..."
        self.db = dbase.MpsdDB(DB_PATH)

        # set up logging
        initialize_logger(self.log_file, log_level=log_level, stdout=not fork)

    def validConfig():
        """
        Returns False if configured options are invalid.
        """
        is_valid = True
        if self.poll_frequency < 1:
            log.error("Poll Frequency must be >= 1")
            is_valid = False
        elif self.add_threshold < 0 or self.add_threshold > 1:
            log.error("Add threshold must be between 0 and 1.")
            is_valid = False
        return is_valid

    def generateStats(self):
        if not os.access(self.template, os.F_OK):
            print >> sys.stderr, "Invalid template file %s" % self.template
        cmd = self.stats_script if self.stats_script else "sqltd"
        rc = os.system("%s %s < %s" % (cmd, self.db.path, self.template))
        if rc == 127:
            print "Error: %s could not be found." % cmd
            exit(1)
        elif rc != 0:
            print "Error: Could not generate statistics"
            exit(1)

    def eventLoop(self):
        """
        The main event loop for mpsd.
        """
        trackID = None  # the id of the playing track
        total = 0       # total time played in the track
        prevDate = None # the time when the previous was added
        while True:
            status = self.mpd.getStatus()
            if not status:
                mpd.disconnect()
                while not self.mpd.connect():
                    log.debug("Attempting reconnect")
                    time.sleep(self.poll_frequency)
                log.debug("Connected!")
                if self.password:
                    self.mpd.authenticate(self.password)
            elif status['state'] == 'play':
                currentSong = self.mpd.getCurrentSong()
                total = total + self.poll_frequency
                if currentSong['id'] != trackID:
                    if prevDate != None:
                        #New track
                        self.db.updateListentime(total, prevDate)
                        total = int(status['time'].rsplit(':')[0])
                        prevDate = None
                    if total >= self.add_threshold*int(currentSong['time']):
                        print currentSong.get('title', 'Unknown Title')
                        try:
                            prevDate = self.db.update(currentSong)
                        except SqlError as e:
                            log.error("Sqlite3 Error: %s\nAdding track: %s\n"
                                    % (e, currentSong))
                        trackID = currentSong['id']
            elif status['state'] == 'stop':
                if prevDate != None:
                    self.db.updateListentime(total, prevDate)
                    total = 0
                    prevDate = None
            time.sleep(self.poll_frequency)

    def run(self):
        """
        Main application run in Daemon
        """
        self.db.connect()

        while not self.mpd.connect():
            print "Attempting reconnect"
            time.sleep(self.poll_frequency)
        print "Connected!"
        try:
            self.eventLoop()
        except:
            log.error("%s" % (sys.exc_info()[1]))
            raise   # For now, re-raise this exception so mpsd quits
        self.mpd.disconnect()

if __name__ == "__main__":
    action = None

    args = {}
    argc = len(sys.argv)
    for i in range(1,argc):
        if sys.argv[i] == '-h':
            usage()
            sys.exit(0)
        elif sys.argv[i] == '--fg':
            args['fork'] = False
        elif sys.argv[i] == '-d' or sys.argv[i] == '--debug':
            args['log_level'] = logging.DEBUG
        elif sys.argv[i] == '--template':
            if argc <= i+1:
                print "No template file specified for --template."
                exit(1)
            i += 1
            args['template'] = sys.argv[i]
        elif sys.argv[i] in ['start', 'stop', 'restart', 'stats']:
            if action:
                usage()
                print "\nError: Can only specify one of ",
                print "start, stop, restart and stats"
                exit(1)
            action = sys.argv[i]
        else:
            usage()
            print "\nInvalid argument '%s'." % sys.argv[i]
            exit(1)

    mpsd = mpdStatsDaemon(**args)

    if action == 'start':
        log.info("Starting mpsd")
        mpsd.start()
    elif action == 'stop':
        log.info("Stopping mpsd")
        mpsd.stop()
    elif action == 'restart':
        mpsd.restart()
    elif action == 'stats':
        mpsd.generateStats()

