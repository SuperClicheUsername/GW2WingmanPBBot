import json
import ssl
import urllib.request
from datetime import datetime as dt

ssl._create_default_https_context = ssl._create_unverified_context


# Get all the boss ids
with urllib.request.urlopen("http://gw2wingman.nevermindcreations.de/api/bosses") as url:
    bossdump = json.load(url)
fractal_cm_boss_ids = []
strike_boss_ids = []
strike_cm_boss_ids = []
raid_boss_ids = []
raid_cm_boss_ids = []
for key in bossdump.keys():
    if bossdump[key]["type"] == "fractal":
        fractal_cm_boss_ids.append("-" + key)
    elif bossdump[key]["type"] == "strike":
        strike_boss_ids.append(key)
    elif bossdump[key]["type"] == "raid":
        raid_boss_ids.append(key)

# Remove river of souls and pre-dhuum bosses
raid_boss_ids.remove("19828")
raid_boss_ids.remove("19536")
raid_boss_ids.remove("19651")
raid_boss_ids.remove("19691")

fractal_cm_boss_ids.remove("-232543")  # Remove full encounter ai
raid_cm_boss_ids = ["-" + boss_id for boss_id in raid_boss_ids]
# Remove wing 1 and 2 and xera as they dont have CMs
raid_cm_boss_ids[6:].remove("-16246")
strike_boss_ids.remove("21333")  # Remove freezie
strike_cm_boss_ids = ["-" + boss_id for boss_id in strike_boss_ids][5:]

# Grab most recent patch ID
with urllib.request.urlopen("https://gw2wingman.nevermindcreations.de/api/patches") as url:
    patchdump = json.load(url)
mostrecentpatchid = patchdump["patches"][0]["id"]
mostrecentpatchstart = patchdump["patches"][0]["from"]
mostrecentpatchstartdt = dt.strptime(
    mostrecentpatchstart + " 12:30 -0000", "%Y-%m-%d %H:%M %z")

# Grab class specs
with urllib.request.urlopen("https://gw2wingman.nevermindcreations.de/api/classes") as url:
    classdump = json.load(url)
professions = list(classdump.keys())