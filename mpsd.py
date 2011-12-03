#!/usr/bin/env python

import string
import sys
import time
import mpd
import os
import logging as log
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
LOGFORMAT = '%(levelname)s\t%(asctime)s\t%(module)s\t%(message)s'
LOGHANDLER = log.handlers.RotatingFileHandler(LOG_FILE,
                maxBytes=50000, backupCount=5)
CONN_ID = {'host':HOST, 'port':PORT}


def mpdConnect(client, conn_id):
    """
    Connect to mpd
    """
    try:
        #client.connect(client,**conn_id)
        client.connect('localhost', '6600')
    except (mpd.MPDError, SocketError):
        print("Could not connect to ", HOST, ":", PORT)
        return False
    except:
        print("Unexpected error: ", sys.exc_info()[0])
        return False
    else:
        print("Connected to %s:%s" %(HOST, PORT))
        return True


def mpdAuth(client, pword):
    """
    Authenticate mpd connection
    """
    try:
        client.password(pword)
    except mpd.CommandError:
        print("Could not authenticate")
        return False
    except mpd.ConnectionError:
        print("Problems connecting to %s:%s" %(HOST, PORT))
        return False
    except:
        print("Unexpected error: %s", sys.exc_info()[1])
        return False
    else:
        print("Authenticated to %s:%s" %(HOST, PORT))
        return True


def mpdGetStatus(client):
    """
    Get the status of mpd
    """
    try:
        return client.status()
    except mpd.CommandError:
        print("Could not get status")
        return False
    except mpd.ConnectionError:
        print("Problems connecting to %s:%s" %(HOST, PORT))
        return False
    except:
        print("Unexpected error:", sys.exc_info()[1])
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
                print("Attempting reconnect")
                time.sleep(POLL_FREQUENCY)
            print("Connected!")
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
    daemon = mpdStatsDaemon('/tmp/mpsd.pid', stdout=LOG_FILE, stderr=LOG_FILE)
    logging.basicConfig(filename=LOG_FILE, format=LOGFORMAT, handler=LOGHANDLER, level=logging.DEBUG)
    if len(sys.argv) >= 2:
        if 'start' == sys.argv[1]:
            if not validConfig():
                exit(1)
            log.info("Starting mpsd")
            daemon.start()
            #daemon.run()
        elif 'stop' == sys.argv[1]:
            log.info("Stopping mpsd")
            daemon.stop()
        elif 'restart' == sys.argv[1]:
            daemon.restart()
        elif 'stats' == sys.argv[1]:
            if len(sys.argv) == 3:
                generateStats(sys.argv[2])
            else:
                generateStats(STATS_TEMPLATE)
        else:
            print("Unknown command")
            print("usage: %s start|stop|restart|stats [stats_template]"
                    % sys.argv[0])
            sys.exit(2)
        sys.exit(0)
    else:
        print("usage: %s start|stop|restart|stats [stats_template]"
                % sys.argv[0])
        sys.exit(2)

