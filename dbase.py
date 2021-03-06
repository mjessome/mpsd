import sqlite3
import os
import time
import logging

log = logging.getLogger('mpsd')

class MpsdDB(object):
    def __init__(self, path):
        self.path = path

    def connect(self):
        """
        Connect to the specified database
        """
        dne = False
        c = None

        if not (os.access(self.path, os.F_OK)):
            dne = True
        try:
            self.db = sqlite3.connect(self.path)
            c = self.db.cursor()
        except sqlite3.Error as err:
            log.error("%s" % (err.args[0]))
            return None

        c.execute('''PRAGMA foreign_key = ON''')
        if dne:
            c.execute('''CREATE TABLE artist (
                    id          INTEGER, \
                    name        TEXT, \
                    PRIMARY KEY (id) \
                    )''')
            c.execute('''CREATE TABLE album ( \
                    id          INTEGER, \
                    title       TEXT, \
                    date        INTEGER, \
                    artist      INTEGER, \
                    FOREIGN KEY (artist) REFERENCES artist (id), \
                    PRIMARY KEY (id) \
                    )''')
            c.execute('''CREATE TABLE track ( \
                    id          INTEGER, \
                    num         INTEGER, \
                    title       TEXT, \
                    artist      INTEGER, \
                    length      INTEGER, \
                    genre       TEXT, \
                    album       INTEGER, \
                    FOREIGN KEY (album) REFERENCES album (id), \
                    FOREIGN KEY (artist) REFERENCES artist (id) \
                    PRIMARY KEY (id) \
                    )''')
            c.execute('''CREATE TABLE listened ( \
                    track       INTEGER, \
                    date        TEXT, \
                    listentime      INTEGER, \
                    FOREIGN KEY (track) REFERENCES track(id), \
                    PRIMARY KEY (track, date) \
                    )''')
                    #Dates are stored "YYYY-MM-DD HH:MM:SS"
            self.db.commit()

    def getInfo(self, info):
        """
        Get all the info from the dictionary and return a full,
        properly formatted dict that will be used
        """
        #Add a log of badly tagged files?

        rval = {}
        # artist/albumartist
        rval['albumartist'] = info.get('albumartist', 'Unkown Artist')
        rval['artist'] = info.get('artist', rval['albumartist'])
        # date
        rval['date'] = info.get('date', '')
        rval['date'] = int(rval['date'].rsplit('-')[0])
        # track
        rval['track'] = info.get('track', '0')
        rval['track'] = int(rval['track'].rsplit('/')[0])
        # genre
        rval['genre'] = info.get('genre', 'Unknown')
        if isinstance(rval['genre'], (list, tuple)):
            rval['genre'] = rval['genre'][0]
        # other
        rval['title'] = info.get('title', 'Unknown Track')
        rval['album'] = info.get('album', 'Unknown Album')
        rval['time'] = int(info['time'])

        return rval

    def update(self, track):
        """
        Update the database with the given info
        """
        id = {}
        info = self.getInfo(track)
        c = self.db.cursor()
        # Artist and AlbumArtist
        for a in ("artist", "albumartist"):
            c.execute('''SELECT id FROM artist \
                    WHERE name=?''', [info[a]])
            row = c.fetchone()
            if row == None:
                #add the artist
                c.execute('''INSERT INTO artist VALUES \
                        (?,?)''', (None, info[a]))
                self.db.commit()
                id[a] = c.lastrowid
                log.debug("Adding new %s: %s, id: %s" % (a, info[a], id[a]))
            else:
                id[a] = int(row[0])

            if(info['artist'] == info['albumartist']):
                #Must be a better way...
                id['albumartist'] = id[a]
                break
        # Album
        c.execute('''SELECT id FROM album WHERE title=?''', [info['album']])
        row = c.fetchone()
        if row == None:
            # add the album
            c.execute('''INSERT INTO album VALUES \
                     (?, ?, ?, ?)''',
                     (None, info['album'], info['date'],
                        id['albumartist']))
            self.db.commit()
            id['album'] = c.lastrowid
            log.debug("Adding new album: %s, id: %s"
                    % (info['album'], id['album']))
        else:
            id['album'] = int(row[0])
        # Track
        c.execute('''SELECT id,title \
               FROM track \
               WHERE title=? AND album=?''',
               (info['title'], id['album']))
        row = c.fetchone()
        if row == None:
            # add the track
            c.execute('''INSERT INTO track VALUES (?,?,?,?,?,?,?)''',
                     (None, info['track'], info['title'], id['artist'],
                      info['time'], info['genre'], id['album']))
            self.db.commit()
            id['track'] = c.lastrowid
            log.debug("Adding new track: %s. %s, id: %s"
                    % (info['track'], info['title'], id['track']))
        else:
            id['track'] = int(row[0])

        # Listened Table insert
        t = time.strftime('%Y-%m-%d %H:%M:%S')
        c.execute('''INSERT INTO listened VALUES \
                 (?, ?, 0)''',
                 (id['track'], t))
        self.db.commit()
        log.info("Added track: %(artist)s - %(album)s - %(track)s. %(title)s"
                % info)
        return t

    def updateListentime(self, total, date):
        c = self.db.cursor()
        c.execute('''UPDATE listened SET listentime=? WHERE date=?''',
                (total, date))
        self.db.commit()
        log.debug("Updated listentime to %d" % (total))

