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
FILE_HANDLER = logging.handlers.RotatingFileHandler(filename=LOG_FILE,
                        maxBytes=50000, backupCount=5)
STDOUT_HANDLER = logging.StreamHandler()
LOG_FORMAT = '%(levelname)s\t%(asctime)s\t%(module)s\t%(message)s'

CONN_ID = {'host':HOST, 'port':PORT}


def usage():
    print("usage: %s [--fg] (start|stop|restart|stats [stats_template])"
            % sys.argv[0])

def mpdConnect(client, conn_id):
    """
    Connect to mpd
    """
    try:
        #client.connect(client,**conn_id)
        client.connect('localhost', '6600')
    except (mpd.MPDError, SocketError):
        log.error("Could not connect to ", HOST, ":", PORT)
        return False
    except:
        log.error("Unexpected error: ", sys.exc_info()[0])
        return False
    else:
        log.info("Connected to %s:%s" %(HOST, PORT))
        return True


def mpdAuth(client, pword):#
    """
    Authenticate mpd connection
    """
    try:
        client.password(pword)
    except mpd.CommandError:
        log.error("Could not authenticate")
        return False
    except mpd.ConnectionError:
        log.error("Problems connecting to %s:%s" %(HOST, PORT))
        return False
    except:
        log.error("Unexpected error: %s", sys.exc_info()[1])
        return False
    else:
        log.info("Authenticated to %s:%s" %(HOST, PORT))
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
        log.error("Problems connecting to %s:%s" %(HOST, PORT))
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
        return client.currentsong()
    except (mpd.MPDError, SocketTimeout) as err:
        log.error("Could not get status: %s" % (err))
        return {}


def eventLoop(client, db):
    trackID = -1    # let -1 mean that no track has been played yet.
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
                    print(currentSong['title'])
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
        print("Error: Poll Frequency must be >= 1")
        return False
    if ADD_THRESHOLD < 0 or ADD_THRESHOLD > 1:
        print("Error: Add threshold must be between 0 and 1.")
        return False
    return True


class mpdStatsDaemon(Daemon):
    def run(self):
        client = mpd.MPDClient()
        db = dbase.dbConnect(DB_PATH)

        while True:
            while not mpdConnect(client, CONN_ID):
                print("Attempting reconnect")
                time.sleep(POLL_FREQUENCY)
            print("Connected!")
            if PASSWORD:
                mpdAuth(client, PASSWORD)
            try:
                eventLoop(client, db)
            except:
                e = sys.exc_info()[1]
                log.error("ERROR: %s" % (e))
                raise   # For now, re-raise this exception so mpsd quits

        mpdGetStatus(client)
        log.debug("%s" % mpdGetStatus(client))

        client.disconnect()


def generateStats(template):
    cmd = STATS_SCRIPT if STATS_SCRIPT else "sqltd"

    rc = os.system(cmd+" "+DB_PATH+" < "+template)

    if rc == 127:
        print("Error: %s could not be found." % cmd)
        exit(1)
    elif rc != 0:
        print("Error: Could not generate statistics")
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
            log.addHandler(STDOUT_HANDLER)
        for a in ['start', 'stop', 'restart', 'stats']:
            if a in sys.argv:
                if action != None:
                    usage()
                    print("\nError: Can only specify one of stat, stop, restart and stats")
                    exit(1)
                action = a

    daemon = mpdStatsDaemon('/tmp/mpsd.pid')
    #daemon = mpdStatsDaemon('/tmp/mpsd.pid', stdout=LOG_FILE, stderr=LOG_FILE)
    log.setLevel(logging.DEBUG)
    FILE_HANDLER.setFormatter(logging.Formatter(LOG_FORMAT))
    log.addHandler(FILE_HANDLER)

    if action == None:
        usage()
        print("\nError: One of start, stop, restart or stats must be specified.")
        sys.exit(2)
    elif action == 'start':
        if not validConfig():
            exit(1)
        log.info("Starting mpsd")
        daemon.start() if not foreground else daemon.run()
    elif action == 'stop':
        log.info("Stopping mpsd")
        daemon.stop()
    elif action == 'restart':
        daemon.restart()
    elif action == 'stats':
        for i in range(len(sys.argv)):
            if sys.argv[i] == 'stats':
                if len(sys.argv) > i+1:
                    generateStats(sys.argv[i+1])
                else:
                    generateStats(STATS_TEMPLATE)
                break
    sys.exit(0)
