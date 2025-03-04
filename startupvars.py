import json
import sqlite3
import ssl
import urllib.request
from datetime import datetime as dt

ssl._create_default_https_context = ssl._create_unverified_context


def initializedb(dbfilename):
    con = sqlite3.connect(dbfilename)
    cur = con.cursor()
    cur.execute(
        """CREATE TABLE bossserverchannels(
        id integer, 
        boss_id text,
        type text)"""
    )  # Server channels to ping
    cur.execute(
        """CREATE TABLE users( 
        id integer, 
        apikey text, 
        boss_id integer, 
        lastchecked text)"""
    )  # User data
    con.commit()
    con.close()
    return None


# Get all the boss ids
with urllib.request.urlopen(
    "http://gw2wingman.nevermindcreations.de/api/bosses"
) as url:
    bossdump = json.load(url)
fractal_cm_boss_ids = []
strike_boss_ids = []
strike_cm_boss_ids = []
raid_boss_ids = []
raid_cm_boss_ids = []
golem_ids = []
bossidtoname = {}
for key in bossdump.keys():
    if bossdump[key]["type"] == "fractal":
        fractal_cm_boss_ids.append(f"-{key}")
    elif bossdump[key]["type"] == "strike":
        strike_boss_ids.append(key)
    elif bossdump[key]["type"] == "raid":
        raid_boss_ids.append(key)
    elif bossdump[key]["type"] == "golem":
        golem_ids.append(key)
    bossidtoname[key] = bossdump[key]["name"]


fractal_cm_boss_ids.remove("-232543")  # Remove full encounter ai
raid_cm_boss_ids = [f"-{boss_id}" for boss_id in raid_boss_ids]
# Remove wing 1 and 2 and xera as they dont have CMs
raid_cm_boss_ids[6:].remove("-16246")
strike_boss_ids.remove("21333")  # Remove freezie
strike_cm_boss_ids = [f"-{boss_id}" for boss_id in strike_boss_ids][5:]

all_boss_ids = (
    fractal_cm_boss_ids
    + strike_boss_ids
    + strike_cm_boss_ids
    + raid_boss_ids
    + raid_cm_boss_ids
)

boss_content_lists = {
    "raids": raid_boss_ids,
    "raids cm": raid_cm_boss_ids,
    "strikes": strike_boss_ids,
    "strikes cm": strike_cm_boss_ids,
    "fractals": fractal_cm_boss_ids,
    "golem": golem_ids,
    "all": all_boss_ids,
}

raid_id_set = set(raid_boss_ids + raid_cm_boss_ids)
fractal_id_set = set(fractal_cm_boss_ids)
strike_id_set = set(strike_boss_ids + strike_cm_boss_ids)
all_id_set = set(all_boss_ids)

boss_content_sets = {
    "raids": raid_id_set,
    "strikes": strike_id_set,
    "fractals": fractal_id_set,
    "all": all_id_set,
}
example_boss_ids = {
    "raids": "19450",
    "strikes": "22343",
    "fractals": "-17759",
    "golem": "16199",
}


def patchIDdump():
    # Grab most recent patch ID
    with urllib.request.urlopen(
        "https://gw2wingman.nevermindcreations.de/api/patches"
    ) as url:
        patchdump = json.load(url)
    mostrecentpatchid = patchdump["patches"][0]["id"]
    mostrecentpatchstart = patchdump["patches"][0]["from"]
    mostrecentpatchstartdt = dt.strptime(
        f"{mostrecentpatchstart} 12:30 -0000", "%Y-%m-%d %H:%M %z"
    )
    patchidlist = [patch["id"] for patch in patchdump["patches"]]
    return (
        patchidlist,
        mostrecentpatchid,
        mostrecentpatchstart,
        mostrecentpatchstartdt,
    )


(
    patchidlist,
    mostrecentpatchid,
    mostrecentpatchstart,
    mostrecentpatchstartdt,
) = patchIDdump()

# Grab class specs
with urllib.request.urlopen(
    "https://gw2wingman.nevermindcreations.de/api/classes"
) as url:
    classdump = json.load(url)
professions = list(classdump.keys())
