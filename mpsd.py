#!/usr/bin/env python

import string
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
from daemon import Daemon

#-------------------------------------------
# Change the following to suit your system
#

# MPD Info
HOST = 'localhost'
PORT = '6600'
#If no password, set to False
PASSWORD = False

# DB Info
DB_PATH = "/var/local/mpsd.db"

# Log File
LOG_FILE = "/var/log/mpd/mpsd.log"

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

CONN_ID = {'host':HOST, 'port':PORT}

def usage():
    print "Usage:"
    print "  mpsd [OPTION] (start|stop|restart|stats [stats_template])\n"
    print "Music Player Stats Daemon - a daemon for recording stats from MPD"

    print "\nRequired Arguments:"
    print "  One of (start|stop|restart|stats [stats_template]):"
    print "    start\n\tStart mpsd"
    print "    stop\n\tStop the currently running mpsd instance"
    print "    restart\n\tRestart the currently running mpsd instance"
    print "    stats [stats_template]"
    print "    \tGenerate statistics using the specified template file."

    print "\nOptional Arguments:"
    print "  -c, --config <FILE>\n\tSpecify the config file (not implemented)"
    print "  -d, --debug\n\tSet logging mode to debug"
    print "  --fg\n\tRun mpsd in the foreground"
    print "  -h, --help\n\tShow this help message"


def initialize_logger(logfile, stdout=False):
    fhandler = logging.handlers.RotatingFileHandler(filename=logfile,
                        maxBytes=50000, backupCount=5)
    fhandler.setFormatter(logging.Formatter(LOG_FORMAT))
    log.setLevel(LOG_LEVEL)
    log.addHandler(fhandler)

    if stdout:
        shandler = logging.StreamHandler()
        shandler.setFormatter(logging.Formatter(STDOUT_FORMAT))
        log.addHandler(shandler)


def mpdConnect(client, conn_id):
    """
    Connect to mpd
    """
    try:
        client.connect(**conn_id)
    except (mpd.MPDError, SocketError):
        log.debug("Could not connect to %(host)s:%(port)s" % (conn_id))
        return False
    except:
        log.error("Unexpected error: %s" % (sys.exc_info()[1]))
        return False
    else:
        log.info("Connected to %(host)s:%(port)s" % (conn_id))
        return True


def mpdAuth(client, pword):
    """
    Authenticate mpd connection
    """
    try:
        client.password(pword)
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


def mpdGetStatus(client):
    """
    Get the status of mpd
    """
    try:
        return client.status()
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


def mpdCurrentSong(client):
    """
    Get the current song
    """
    try:
        curSong = client.currentsong()
        for k in curSong.keys():
            if isinstance(curSong[k], (tuple, list)):
                curSong[k] = curSong[k][0]
            curSong[k] = unicode(curSong[k], 'utf-8')
        return curSong
    except (mpd.MPDError, SocketTimeout):
        log.error("Could not get status: %s" % (sys.exc_info()[1]))
        return {}


def eventLoop(client, db):
    trackID = None  # the id of the playing track
    total = 0       # total time played in the track
    prevDate = None # the time when the previous was added
    while True:
        status = mpdGetStatus(client)
        if not status:
            client.disconnect();
            while not mpdConnect(client, CONN_ID):
                log.debug("Attempting reconnect")
                time.sleep(POLL_FREQUENCY)
            log.debug("Connected!")
            if PASSWORD:
                mpdAuth(client, PASSWORD)
        elif status['state'] == 'play':
            currentSong = mpdCurrentSong(client)
            total = total + POLL_FREQUENCY
            #print "Current total: " + str(total)
            #print "Current time: " + str(status['time'].rsplit(':')[0])
            if currentSong['id'] != trackID:
                if prevDate != None:
                    #New track
                    dbase.updateListentime(db, total, prevDate)
                    total = int(status['time'].rsplit(':')[0])
                    prevDate = None
                if total >= ADD_THRESHOLD*int(currentSong['time']):
                    print currentSong.get('title', 'Unknown Title')
                    try:
                        prevDate = dbase.dbUpdate(db, currentSong)
                    except SqlError as e:
                        log.error("Sqlite3 Error: %s\nAdding track: %s\n"
                                % (e, currentSong))
                    trackID = currentSong['id']
        elif status['state'] == 'stop':
            if prevDate != None:
                dbase.updateListentime(db, total, prevDate);
                total = 0
                prevDate = None
        time.sleep(POLL_FREQUENCY)


def validConfig():
    if POLL_FREQUENCY < 1:
        log.error("Poll Frequency must be >= 1")
        return False
    if ADD_THRESHOLD < 0 or ADD_THRESHOLD > 1:
        log.error("Add threshold must be between 0 and 1.")
        return False
    return True


class mpdStatsDaemon(Daemon):
    def run(self):
        client = mpd.MPDClient()
        db = dbase.dbConnect(DB_PATH)

        while True:
            while not mpdConnect(client, CONN_ID):
                print "Attempting reconnect"
                time.sleep(POLL_FREQUENCY)
            print "Connected!"
            if PASSWORD:
                mpdAuth(client, PASSWORD)
            try:
                eventLoop(client, db)
            except:
                log.error("%s" % (sys.exc_info()[1]))
                raise   # For now, re-raise this exception so mpsd quits

        mpdGetStatus(client)
        log.debug("%s" % mpdGetStatus(client))

        client.disconnect()


def generateStats(template):
    cmd = STATS_SCRIPT if STATS_SCRIPT else "sqltd"
    rc = os.system(cmd+" "+DB_PATH+" < "+template)

    if rc == 127:
        print "Error: %s could not be found." % cmd
        exit(1)
    elif rc != 0:
        print "Error: Could not generate statistics"
        exit(1)

if __name__ == "__main__":
    foreground = False
    action = None

    if len(sys.argv) >= 2:
        if '-h' in sys.argv:
            usage()
            sys.exit(0)
        if '--fg' in sys.argv:
            foreground = True
        if '-d' in sys.argv or '--debug' in sys.argv:
            LOG_LEVEL = logging.DEBUG
        for a in ['start', 'stop', 'restart', 'stats']:
            if a in sys.argv:
                if action != None:
                    usage()
                    print "\nError: Can only specify one of start, stop, restart and stats"
                    exit(1)
                action = a

    daemon = mpdStatsDaemon('/tmp/mpsd.pid', fork=not foreground)

    if action == None:
        usage()
        print "\nError: One of start, stop, restart or stats must be specified."
        sys.exit(2)
    elif action == 'stats':
        for i in range(len(sys.argv)):
            if sys.argv[i] == 'stats':
                if len(sys.argv) > i+1:
                    generateStats(sys.argv[i+1])
                else:
                    generateStats(STATS_TEMPLATE)
                break
        sys.exit(0)

    # Initialize the logger now, since stats shouldn't
    # require root access.
    initialize_logger(LOG_FILE, stdout=foreground)

    # Daemon actions
    if action == 'start':
        if not validConfig():
            exit(1)
        log.info("Starting mpsd")
        daemon.start()
    elif action == 'stop':
        log.info("Stopping mpsd")
        daemon.stop()
    elif action == 'restart':
        daemon.restart()
    sys.exit(0)
