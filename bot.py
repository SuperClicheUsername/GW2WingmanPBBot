import importlib
import json
import pickle
import sqlite3
import ssl
import urllib.request
from datetime import datetime as dt
from datetime import timezone
from os.path import exists
from typing import Literal

import discord
import requests
from discord import app_commands
from discord.ext import commands, tasks
from discord.utils import get

import startupvars
from startupvars import *

ssl._create_default_https_context = ssl._create_unverified_context

description = """A bot to pull personal best and leaderboard info from gw2wingman."""

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="?", description=description, intents=intents)

dbfilename = "data/wingmanbot.db"
if not exists(dbfilename):
    initializedb(dbfilename)
global con
con = sqlite3.connect(dbfilename)
global cur
cur = con.cursor()


def getAleevaToken():
    with open("data/aleeva_token.txt") as f:
        token = f.readline()
    return token


def savedata():
    with open("data/workingdata.pkl", "wb") as f:
        pickle.dump(workingdata, f)
    return None


def isapikeyvalid(key):
    with urllib.request.urlopen(
        "https://gw2wingman.nevermindcreations.de/api/getPlayerStats?apikey={}".format(
            key
        )
    ) as url:
        playerstatdump = json.load(url)
    if "error" in playerstatdump.keys():
        return False
    else:
        return True


def logtimestampfromlink(link):
    format_data = "%Y%m%d-%H%M%S %z"
    # 1 dash is Wingman uploader link format
    if link.count("-") == 1:
        timestamp = link[:15] + " -0500"
    # 2 dashes is dps report link format
    elif link.count("-") == 2:
        timestamp = link[5:20] + " -0500"
    timestamp = dt.strptime(timestamp, format_data)
    return timestamp


# Use the Aleeva API endpoint to request discord ID
def discordIDfromAcctName(names):
    endpoint = (
        "https://api.aleeva.io/server/826421836992348171/member_search?account_names="
    )
    headers = {"Authorization": "Bearer " + aleeva_token}
    missingnames = []

    # TODO: Caching account names
    # for name in names:
    #     if name in cachedAcctNames:
    #         id = cachedAcctNames[name]
    #     else:
    #         missingnames.append(name)
    missingnames = names.copy()  # Remove later

    data = ",".join(missingnames)
    response = requests.get(endpoint + data, headers=headers)

    # If the response doesnt work
    if response.status_code != 200:
        print(response.json())
        return False

    # Update cached account names
    # cachedAcctNames = cachedAcctNames | response.json()

    id = response.json()

    return id


@bot.event
async def on_ready():
    global workingdata, con, cur, aleeva_token
    with open("data/workingdata.pkl", "rb") as f:
        workingdata = pickle.load(f)
    await bot.tree.sync()

    dbfilename = "data/wingmanbot.db"
    if not exists(dbfilename):
        initializedb(dbfilename)

    # aleeva_token = getAleevaToken() TODO: Aleeva token lookup
    con = sqlite3.connect(dbfilename)
    cur = con.cursor()
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")
    # my_task.start()


@bot.tree.error
async def on_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You must be a server administrator to use this command.", ephemeral=True
        )


@bot.tree.command(description="Add a user to be tracked")
@app_commands.describe(apikey="API Key used in Wingman")
async def adduser(interaction: discord.Interaction, apikey: str):
    if isapikeyvalid(apikey):
        workingdata["user"][interaction.user.id] = {
            "apikey": None,
            "tracked_boss_ids": set(),
            "lastchecked": None,
        }
        workingdata["user"][interaction.user.id]["apikey"] = apikey
        await interaction.response.send_message(
            "Valid API key. Saving. Do /track next", ephemeral=True
        )
        savedata()
    else:
        await interaction.response.send_message(
            "Invalid API key try again.", ephemeral=True
        )


@bot.tree.command(description="Start tracking bosses")
@app_commands.describe(choice="The content you want to track")
async def track(
    interaction: discord.Interaction,
    choice: Literal["fractals", "raids", "raids cm", "strikes", "strikes cm", "golem"],
):
    user = interaction.user.id
    if user not in workingdata["user"].keys():
        await interaction.response.send_message(
            "You are not a registered user. Do /adduser"
        )
        return

    if choice == "fractals":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user][
            "tracked_boss_ids"
        ].union(fractal_cm_boss_ids)
    elif choice == "raids":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user][
            "tracked_boss_ids"
        ].union(raid_boss_ids)
    elif choice == "raids cm":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user][
            "tracked_boss_ids"
        ].union(raid_cm_boss_ids)
    elif choice == "strikes":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user][
            "tracked_boss_ids"
        ].union(strike_boss_ids)
    elif choice == "strikes cm":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user][
            "tracked_boss_ids"
        ].union(strike_cm_boss_ids)
    elif choice == "golem":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user][
            "tracked_boss_ids"
        ].union(golem_ids)
    await interaction.response.send_message(
        "Added bosses to track list. Next /check will not give PBs to reduce spam.",
        ephemeral=True,
    )
    # Dont spam next time they do /check
    workingdata["user"][user]["lastchecked"] = None
    savedata()


@bot.tree.command(description="Manually check for new PBs")
# @app_commands.describe()
async def check(interaction: discord.Interaction):
    userid = interaction.user.id
    responses = []
    if (
        workingdata["user"][userid]["apikey"] is not None
        and workingdata["user"][userid]["tracked_boss_ids"] != set()
    ):
        APIKey = workingdata["user"][userid]["apikey"]
        tracked_boss_ids = workingdata["user"][userid]["tracked_boss_ids"]

        # Don't link logs if lastchecked is none or before most recent patch
        if (
            workingdata["user"][userid]["lastchecked"] is None
            or workingdata["user"][userid]["lastchecked"] < mostrecentpatchstartdt
        ):
            await interaction.response.send_message(
                "You haven't checked logs yet this patch. Not linking PBs to reduce spam. Next time /check will link all PB logs",
                ephemeral=True,
            )
            workingdata["user"][userid]["lastchecked"] = dt.now(
                timezone.utc
            )  # Update last checked
            savedata()
            return

        with urllib.request.urlopen(
            "https://gw2wingman.nevermindcreations.de/api/getPlayerStats?apikey={}".format(
                APIKey
            )
        ) as url:
            playerstatdump = json.load(url)

        # Look for new top dps log
        topstats = playerstatdump["topPerformances"][mostrecentpatchid]
        bossescleared = list(set(tracked_boss_ids).intersection(topstats.keys()))
        for boss in bossescleared:
            # Remove negative from id if present so we can pull boss name from api
            if boss.startswith("-"):
                boss_id = boss[1:]
            else:
                boss_id = boss
            specscleared = list(set(topstats[boss].keys()).intersection(professions))
            for spec in specscleared:
                logtimestamp = logtimestampfromlink(topstats[boss][spec]["link"])
                # Check if log timestamps are from after last check
                if logtimestamp > workingdata["user"][userid]["lastchecked"]:
                    responses.append(
                        "New best DPS log on {}!\nSpec: {}\nDPS: {}\nLink: https://gw2wingman.nevermindcreations.de/log/{}".format(
                            bossdump[boss_id]["name"],
                            spec,
                            topstats[boss][spec]["topDPS"],
                            topstats[boss][spec]["link"],
                        )
                    )

        # Look for new fastest log
        toptimes = playerstatdump["topBossTimes"][mostrecentpatchid]
        bossescleared = list(set(tracked_boss_ids).intersection(toptimes.keys()))
        for boss in bossescleared:
            # Remove negative from id if present so we can pull boss name from api
            if boss.startswith("-"):
                boss_id = boss[1:]
            else:
                boss_id = boss
            logtimestamp = logtimestampfromlink(toptimes[boss]["link"])
            if logtimestamp > workingdata["user"][userid]["lastchecked"]:
                bosstime = dt.fromtimestamp(
                    toptimes[boss]["durationMS"] / 1000.0
                ).strftime("%M:%S.%f")[:-3]
                responses.append(
                    "New fastest log on {}!\nTime: {}\nLink: https://gw2wingman.nevermindcreations.de/log/{}".format(
                        bossdump[boss_id]["name"], bosstime, toptimes[boss]["link"]
                    )
                )

        if responses == []:
            await interaction.response.send_message("No new PBs")
        else:
            await interaction.response.defer()
            for response in responses:
                await interaction.followup.send(response)

        workingdata["user"][userid]["lastchecked"] = dt.now(
            timezone.utc
        )  # Update last checked
        savedata()
    elif workingdata["user"][userid]["apikey"] is None:
        await interaction.response.send_message(
            "Error. You need to add your api key first. Do /useradd"
        )
    else:
        await interaction.response.send_message(
            "Error. You don't have any tracked bosses. Do /track"
        )


@bot.tree.command(description="Add tracking for when game adds new boss")
@app_commands.describe(newbossid="Positive new boss id")
@commands.is_owner()
async def addnewbossid(interaction: discord.Interaction, bosstype: Literal["fractals", "raids", "strikes", "golem"], newbossid: str):
    # My discord ID so only I can use this command
    # This if statement is unecessary if is_owner works.
    adminuserid = 204614061206405120
    if interaction.user.id == adminuserid:
        # Example boss of each type we search to find channels with each type
        if bosstype == "raids":
            bossid = "19450"
        elif bosstype == "strikes":
            bossid = "22343"
        elif bosstype == "fractals":
            bossid = "-17759"
        elif bosstype == "golem":
            bossid = "16199"
            
        selectsql = f"""SELECT DISTINCT id, type FROM bossserverchannels WHERE boss_id = '{bossid}'"""
        insertsql = """INSERT INTO bossserverchannels VALUES(?,?,?)"""

        cur.execute(selectsql)
        rows = cur.fetchall()
        dpschannelids = [item[0] for item in rows if item[1] == "dps"]
        timechannelids = [item[0] for item in rows if item[1] == "time"]

        for channel_id in dpschannelids:
            cur.execute(insertsql, (channel_id, newbossid, "dps"))
        for channel_id in timechannelids:
            cur.execute(insertsql, (channel_id, newbossid, "time"))
        con.commit()

        numservers = len(rows)
        await interaction.response.send_message(f"Success! Added boss {numservers} times")
    else:
        await interaction.response.send_message("Only the bot admin can use this command", ephemeral=True)


@bot.tree.command(description="Add tracking for when game adds new boss")
@app_commands.describe(newbossid="Positive new boss id")
@commands.is_owner()
async def removenewbossid(interaction: discord.Interaction, bosstype: Literal["fractals", "raids", "strikes", "golem"], newbossid: str):
    # My discord ID so only I can use this command
    # This if statement is unecessary if is_owner works.
    adminuserid = 204614061206405120
    if interaction.user.id == adminuserid:
        # Example boss of each type we search to find channels with each type
        if bosstype == "raids":
            bossid = "19450"
        elif bosstype == "strikes":
            bossid = "22343"
        elif bosstype == "fractals":
            bossid = "-17759"
        elif bosstype == "golem":
            bossid = "16199"
            
        selectsql = f"""SELECT DISTINCT id, type FROM bossserverchannels WHERE boss_id = '{bossid}'"""
        

        cur.execute(selectsql)
        rows = cur.fetchall()
        dpschannelids = [item[0] for item in rows if item[1] == "dps"]
        timechannelids = [item[0] for item in rows if item[1] == "time"]

        for channel_id in dpschannelids:
            deletesql = """DELETE FROM bossserverchannels WHERE id = ? AND boss_id = ? AND type = ?"""
            cur.execute(deletesql, (channel_id, newbossid, "dps"))
        for channel_id in timechannelids:
            deletesql = """DELETE FROM bossserverchannels WHERE id = ? AND boss_id = ? AND type = ?"""
            cur.execute(deletesql, (channel_id, newbossid, "time"))
        con.commit()

        numservers = len(rows)
        await interaction.response.send_message(f"Success! Removed boss {numservers} times")
    else:
        await interaction.response.send_message("Only the bot admin can use this command", ephemeral=True)



# @bot.tree.command(
#     description="Debug command to reset last checked to most recent patch day"
# )
# # @app_commands.describe()
# async def resetlastchecked(interaction: discord.Interaction):
#     userid = interaction.user.id
#     if userid not in workingdata["user"].keys():
#         await interaction.response.send_message(
#             "You are not a registered user. Do /adduser", ephemeral=True
#         )
#         return

#     workingdata["user"][userid]["lastchecked"] = None
#     await interaction.response.send_message(
#         "Last checked reset to most recent patch day", ephemeral=True
#     )


# @bot.tree.command(description="Responds with the last time PBs were checked")
# # @app_commands.describe()
# async def lastchecked(interaction: discord.Interaction):
#     userid = interaction.user.id
#     if userid not in workingdata["user"].keys():
#         await interaction.response.send_message(
#             "You are not a registered user. Do /adduser", ephemeral=True
#         )
#         return
#     if workingdata["user"][userid]["lastchecked"] is None:
#         await interaction.response.send_message(
#             "You have never checked logs before.", ephemeral=True
#         )
#         return

#     lastchecked = workingdata["user"][userid]["lastchecked"]
#     delta = dt.now(timezone.utc) - lastchecked
#     days, remainder = divmod(delta.total_seconds(), 86400)
#     hours, remainder = divmod(remainder, 3600)
#     minutes, _ = divmod(remainder, 60)

#     await interaction.response.send_message(
#         "Last checked "
#         + f"{int(days)} days, {int(hours)} hours, {int(minutes)} minutes"
#         + " ago",
#         ephemeral=True,
#     )


@bot.tree.command(description="Link about info")
async def about(interaction: discord.Interaction):
    embed = discord.Embed(
        title="View github",
        url="https://github.com/SuperClicheUsername/GW2WingmanPBBot",
    )
    await interaction.response.send_message(
        "Discord bot to help track personal bests and patch records from GW2Wingman. Contact Discord name: supercliche.",
        embed=embed,
    )


@bot.tree.command(
    description="Track bosses to be automatically pinged in channel where command is called on new patch record"
)
@app_commands.describe(choice="The content you want to track")
@app_commands.checks.has_permissions(administrator=True)
@commands.guild_only()
async def channeltrackboss(
    interaction: discord.Interaction,
    pingtype: Literal["dps", "time"],
    choice: Literal["fractals", "raids", "raids cm", "strikes", "strikes cm", "golem", "all"],
):
    channel_id = interaction.channel_id
    sql = """INSERT INTO bossserverchannels VALUES(?,?,?)"""
    if choice == "fractals":
        for boss_id in fractal_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
            con.commit()
    elif choice == "raids":
        for boss_id in raid_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
            con.commit()
    elif choice == "raids cm":
        for boss_id in raid_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
            con.commit()
    elif choice == "strikes":
        for boss_id in strike_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
            con.commit()
    elif choice == "strikes cm":
        for boss_id in strike_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
            con.commit()
    elif choice == "all":
        for boss_id in all_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
            con.commit()
    elif choice == "golem":
        if pingtype == "time":
            await interaction.response.send_message("Only DPS pingtype is supported for golems. Try again.")
            return

        for boss_id in golem_ids:
            cur.execute(sql, (channel_id, boss_id, "dps"))
            con.commit()

    await interaction.response.send_message(
        "Added bosses to track list. Will ping channel when next patch record is posted",
    )
    return


@bot.tree.command(
    description="Untrack bosses from automatic ping list when a new patch record is added"
)
@app_commands.describe(choice="The content you want to track")
@app_commands.checks.has_permissions(administrator=True)
@commands.guild_only()
async def channeluntrackboss(
    interaction: discord.Interaction,
    pingtype: Literal["dps", "time"],
    choice: Literal["fractals", "raids", "raids cm", "strikes", "strikes cm", "golem", "all"],
):
    channel_id = interaction.channel_id
    sql = """DELETE FROM bossserverchannels WHERE id=? AND boss_id=? AND type=?"""
    if choice == "fractals":
        for boss_id in fractal_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
            con.commit()
    elif choice == "raids":
        for boss_id in raid_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
            con.commit()
    elif choice == "raids cm":
        for boss_id in raid_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
            con.commit()
    elif choice == "strikes":
        for boss_id in strike_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
            con.commit()
    elif choice == "strikes cm":
        for boss_id in strike_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
            con.commit()
    elif choice == "all":
        for boss_id in all_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
            con.commit()
    elif choice == "golem":
        for boss_id in golem_ids:
            cur.execute(sql, (channel_id, boss_id, "dps"))
            con.commit()
    await interaction.response.send_message("Removed bosses from track list.")
    return


# @bot.event
# async def personaldps(content, cur):
#     acctname = content["account"]
#     # TODO: check if acctname is in tracked list
#     bossid = content["bossID"]
#     bossname = content["bossName"]
#     # TODO: check if bossid is in tracked list

#     # Construct message from POSTed content

#     charname = content["character"]
#     profession = content["profession"]
#     overallPB = content["alsoOverallPB"]
#     dps = content["dps"]
#     loglink = content["link"]

#     if overallPB:
#         message = "New personal best DPS log on {}\nClass: {}, also best overall!\nCharacter: {}\nDPS: {}".format(
#             bossname, profession, charname, dps)
#     else:
#         message = "New personal best DPS log on {}\nClass: {}\nCharacter: {}\nDPS: {}".format(
#             bossname, profession, charname, dps)
#     log = discord.Embed(
#         title="Log", url="https://gw2wingman.nevermindcreations.de/log/" + loglink)

#     # Distribute message
#     await bot.wait_until_ready()
#     channel = bot.get_channel(1070109613355192370)
#     bot.loop.create_task(channel.send(message, embed=log))


# @bot.event
# async def personaltime(content, cur):
#     # TODO: check if acctname is in tracked list
#     bossid = content["bossID"]
#     bossname = content["bossName"]
#     # TODO: check if bossid is in tracked list

#     # Construct message from POSTed content

#     players = content["players"]
#     group = content["group_affiliation"]
#     time = dt.fromtimestamp(content["duration"]/1000).strftime('%M:%S.%f')[:-3]
#     loglink = content["link"]

#     if group:
#         message = "New fastest log on {}\nSet by: {}\nPlayers: {}\nTime: {}".format(
#             bossname, group, players, time)
#     else:
#         message = "New fastest log on {}\nPlayers: {}\nTime: {}".format(
#             bossname, players, time)
#     log = discord.Embed(
#         title="Log", url="https://gw2wingman.nevermindcreations.de/log/" + loglink)

#     # Distribute message
#     await bot.wait_until_ready()
#     channel = bot.get_channel(1070109613355192370)
#     bot.loop.create_task(channel.send(message, embed=log))


@bot.event
async def pingreportedlog(content, cur):
    await bot.wait_until_ready()
    loglink = content["link"]
    reasontext = content["reason"]
    bossid = content["bossID"]
    bossname = content["bossName"]
    time = content["duration"]
    reportedlogchannel = 852681966444740620

    log = discord.Embed(
        title="Log reported on {}, reason: {}".format(bossname, reasontext),
        url="https://gw2wingman.nevermindcreations.de/log/" + loglink,
    )
    if bossid.startswith("-"):
        bossid = bossid[1:]
    iconurl = "https://gw2wingman.nevermindcreations.de" + bossdump[bossid]["icon"]
    log.set_thumbnail(url=iconurl)
    log.add_field(name="Time", value=time, inline=True)
    log.add_field(name="Link", value=loglink, inline=True)

    channel = bot.get_channel(reportedlogchannel)
    bot.loop.create_task(channel.send(embed=log))
    print("Log reported {}, reason: {}".format(loglink, reasontext))

@bot.event
async def internalmessage(content, cur):
    # Echos any message sent to the /internalmessage/ endpoint to the internal botspam channel
    await bot.wait_until_ready()
    message = content["message"]
    internalmessagechannel = 1208602365972717628

    channel = bot.get_channel(internalmessagechannel)
    bot.loop.create_task(channel.send(content=message))
    print("Internal message {}".format(message))

@bot.event
async def patchtimerecord(content, cur):
    await bot.wait_until_ready()
    # TODO: check if acctname is in tracked list
    bossid = content["bossID"]
    cur.execute(
        "SELECT DISTINCT id FROM bossserverchannels WHERE boss_id=? AND type=?",
        (bossid, "time"),
    )
    rows = cur.fetchall()

    # Dont keep going if no channel wants the ping
    if not rows:
        print("Nobody wanted this ping")
        return

    #  Negative boss IDs are CMs
    if bossid.startswith("-"):
        # Check for legendary key first because not all bosses will have it
        if "isLegendaryCM" in content.keys():
            if content["isLegendaryCM"]:
                bossname = content["bossName"] + " LCM"
        else:
            bossname = content["bossName"] + " CM"
    else:
        bossname = content["bossName"]

    # Determine era. Reload patchlist if new patch detected
    if content["eraID"] == "all":
        era = "All Time"
    elif content["eraID"] not in patchidlist:
        importlib.reload(startupvars)
        era = "Current Patch"
    elif content["eraID"] == patchidlist[0]:
        era = "Current Patch"
    else:
        print("Record for old patch, ignoring")
        return

    # Construct message from POSTed content

    players = content["players_chars"]
    accts = content["players"]
    groups = ", ".join(content["group"])
    time = dt.fromtimestamp(content["duration"] / 1000).strftime("%M:%S.%f")[:-3]
    prevtime = dt.fromtimestamp(content["previousDuration"] / 1000).strftime(
        "%M:%S.%f"
    )[:-3]
    loglink = content["link"]

    log = discord.Embed(
        title="New fastest log on {}".format(bossname),
        url="https://gw2wingman.nevermindcreations.de/log/" + loglink,
    )
    if groups:
        log.add_field(name="Group", value=groups, inline=False)
        iconurl = content["groupIcons"][0]

        # If no group icon get boss icon
        if (
            iconurl
            == "https://gw2wingman.nevermindcreations.de/static/groupIcons/defGroup.png"
        ):
            if bossid.startswith("-"):
                bossid = bossid[1:]
            iconurl = (
                "https://gw2wingman.nevermindcreations.de" + bossdump[bossid]["icon"]
            )
        log.set_thumbnail(url=iconurl)
    else:
        if bossid.startswith("-"):
            bossid = bossid[1:]
        iconurl = "https://gw2wingman.nevermindcreations.de" + bossdump[bossid]["icon"]
        log.set_thumbnail(url=iconurl)

    log.add_field(name="Time", value=time, inline=True)
    log.add_field(name="Previous Time", value=prevtime, inline=True)
    log.add_field(name="Era", value=era, inline=True)

    emoji_list = []
    for spec in content["players_professions"]:
        emoji = get(bot.emojis, name=spec)
        emoji_list.append(str(emoji))
    playerscontent = [
        m + " " + n + "/" + o for m, n, o in zip(emoji_list, players, accts)
    ]
    playerscontent = "\n".join(playerscontent)

    log.add_field(name="Players", value=playerscontent)

    # Distribute message

    for row in rows:
        channel = bot.get_channel(row[0])
        bot.loop.create_task(channel.send(embed=log))


@bot.event
async def patchdpsrecord(content, cur):
    await bot.wait_until_ready()

    # TODO: check if acctname is in tracked list
    bossid = content["bossID"]

    cur.execute(
        "SELECT DISTINCT id FROM bossserverchannels WHERE boss_id=? AND type=?",
        (bossid, "dps"),
    )
    rows = cur.fetchall()

    # Dont keep going if no channel wants the ping
    if not rows:
        print("Nobody wanted this ping")
        return

    #  Negative boss IDs are CMs
    if bossid.startswith("-"):
        bossname = content["bossName"] + " CM"
    else:
        bossname = content["bossName"]
    
    #  Negative boss IDs are CMs
    if bossid.startswith("-"):
        # Check for legendary key first because not all bosses will have it
        if "isLegendaryCM" in content.keys():
            if content["isLegendaryCM"]:
                bossname = content["bossName"] + " LCM"
        else:
            bossname = content["bossName"] + " CM"
    else:
        bossname = content["bossName"]

    # Determine era. Reload patchlist if new patch detected
    if content["eraID"] == "all":
        era = "All Time"
    elif content["eraID"] not in patchidlist:
        importlib.reload(startupvars)
        era = "Current Patch"
    elif content["eraID"] == patchidlist[0]:
        era = "Current Patch"
    else:
        print("Record for old patch, ignoring")
        return

    charname = content["character"]
    profession = content["profession"]
    dps = content["dps"]
    dpsdiff = dps - content["previousDps"]
    dpsstring = str(dps) + " (+{})".format(dpsdiff)
    acctname = content["account"]

    # idmap = discordIDfromAcctName([acctname])
    # if idmap:
    #    discordID = discordIDfromAcctName([acctname])[acctname][0]

    # Construct message from POSTed content
    groups = ", ".join(content["group"])
    loglink = content["link"]

    log = discord.Embed(
        title="New DPS record log on {}".format(bossname),
        url="https://gw2wingman.nevermindcreations.de/log/" + loglink,
    )
    if groups:
        log.add_field(name="Group", value=groups, inline=False)
        iconurl = content["groupIcons"][0]

        # If no group icon get boss icon
        if (
            iconurl
            == "https://gw2wingman.nevermindcreations.de/static/groupIcons/defGroup.png"
        ):
            if bossid.startswith("-"):
                bossid = bossid[1:]
            iconurl = (
                "https://gw2wingman.nevermindcreations.de" + bossdump[bossid]["icon"]
            )
        log.set_thumbnail(url=iconurl)
    else:
        if bossid.startswith("-"):
            bossid = bossid[1:]
        iconurl = "https://gw2wingman.nevermindcreations.de" + bossdump[bossid]["icon"]
        log.set_thumbnail(url=iconurl)

    log.add_field(name="DPS", value=dpsstring, inline=True)
    log.add_field(name="Era", value=era, inline=True)

    emoji = get(bot.emojis, name=profession)
    playercontent = str(emoji) + " " + charname + "/" + acctname

    log.add_field(name="Player", value=playercontent)

    # Distribute message

    for row in rows:
        channel = bot.get_channel(row[0])
        # If the user is in the guild, ping them.
        # if channel.guild.get_member(discordID):
        #    log.add_field(
        #        name="Mention", value=bot.get_user(discordID).mention, inline=True
        #    )
        bot.loop.create_task(channel.send(embed=log))


with open("data/discord_token.txt") as f:
    token = f.readline()


def run_discord_bot():
    bot.run(token)
