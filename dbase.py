import sqlite3
import os
import time

def dbConnect(db_path):
    """
    Connect to the specified database
    """
    dne = False
    c = None
    db = None

    if not (os.access(db_path, os.F_OK)):
        dne = True

    try:
        db = sqlite3.connect(db_path)
        c = db.cursor()
    except sqlite3.Error as e:
        print("Error: "+e.args[0])
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
        db.commit();

    return db


def getInfo(info):
    """
    Get all the info from the dictionary and return a full,
    properly formatted dict that will be used
    """
    #Add a log of badly tagged files?

    rval = {}

    if 'albumartist' in info:
        rval['albumartist'] = info['albumartist']
    else:
        rval['albumartist'] = ""

    if 'artist' in info:
        rval['artist'] = info['artist']
        if(rval['albumartist'] == ""):
            rval['albumartist'] = rval['artist']
    else:
        if(rval['albumartist'] != ""):
            rval['artist'] = rval['albumartist']
        else:
            rval['albumartist'] = "Unknown Artist"
            rval['artist'] = "Unknown Artist"

    if 'date' in info:
        rval['date'] = int(info['date'].rsplit("-")[0])
    else:
        rval['date'] = 0

    if 'track' in info:
        rval['track'] = int(info['track'].rsplit("/")[0])
    else:
        rval['track'] = 0

    if 'title' in info:
        rval['title'] = info['title']
    else:
        rval['title'] = "Unknown Track"

    if 'album' in info:
        rval['album'] = info['album']
    else:
        rval['album'] = "Unknown Album"

    if 'genre' in info:
        #check if genre is a list
        if type(info['genre']).__name__ == 'list':
            rval['genre'] = info['genre'][0]
        else:
            rval['genre'] = info['genre']
    else:
        rval['genre'] = "Unknown"

    rval['time'] = int(info['time'])

    return rval


def dbUpdate(db, track):
    """
    Update the database with the given info
    """

    info = getInfo(track)

    c = db.cursor()

    id = {}

    #Artist and AlbumArtist
    for a in ("artist", "albumartist"):
        c.execute('''SELECT id FROM artist \
                WHERE name=?''', [info[a]])
        row = c.fetchone()
        if row == None:
            #add the artist
            c.execute('''INSERT INTO artist VALUES \
                    (?,?)''', (None, info[a]))
            db.commit()
            id[a] = c.lastrowid
        else:
            id[a] = int(row[0])

        print("%s: %s, id: %a" % (a, info[a], id[a]))

        if(info['artist'] == info['albumartist']):
            #Must be a better way...
            id['albumartist'] = id[a]
            break

    #Album
    c.execute('''SELECT id FROM album WHERE title=?''', [info['album']])
    row = c.fetchone()
    if row == None:
        #add the album
        c.execute('''INSERT INTO album VALUES \
                 (?, ?, ?, ?)''',
                 (None, info['album'], info['date'],
                    id['albumartist']))
        db.commit()
        id['album'] = c.lastrowid

        print("\tNew Album ID: " + str(id['album']))
    else:
        id['album'] = int(row[0])

    #Track
    c.execute('''SELECT id,title \
           FROM track \
           WHERE title=? AND album=?''',
           (info['title'], id['album']))
    row = c.fetchone()
    if row == None:
        #add the track
        c.execute('''INSERT INTO track VALUES (?,?,?,?,?,?,?)''',
                 (None, info['track'], info['title'], id['artist'],
                  info['time'], info['genre'], id['album']))
        db.commit()
        id['track'] = c.lastrowid
        print("\tNew Track")
    else:
        id['track'] = int(row[0])

    #Listened Table insert
    t = time.strftime('%Y-%m-%d %H:%M:%S')
    c.execute('''INSERT INTO listened VALUES \
             (?, ?, 0)''',
             (id['track'], t))

    db.commit()

    return t


def updateListentime(db, total, date):
    c = db.cursor();
    c.execute('''UPDATE listened SET listentime=? WHERE date=?''', (total, date))
    db.commit()
    print("Updated listentime to " + str(total))

