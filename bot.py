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

@bot.event
async def on_ready():
    global workingdata, con, cur, aleeva_token
    with open("data/workingdata.pkl", "rb") as f:
        workingdata = pickle.load(f)
    await bot.tree.sync()

    dbfilename = "data/wingmanbot.db"
    if not exists(dbfilename):
        initializedb(dbfilename)

    con = sqlite3.connect(dbfilename)
    cur = con.cursor()
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")


@bot.tree.error
async def on_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You must be a server administrator to use this command.", ephemeral=True
        )
    if isinstance(error, commands.CommandInvokeError):
        error = error.original

    if isinstance(error, discord.errors.Forbidden):
        print("Forbidden error. From Guild:")
        print(interaction.guild.name)

@bot.tree.command(description="Add a user to be tracked")
@app_commands.describe(api_key="API Key used in Wingman")
async def adduser(interaction: discord.Interaction, api_key: str):
    if isapikeyvalid(api_key):
        workingdata["user"][interaction.user.id] = {
            "apikey": None,
            "tracked_boss_ids": set(),
            "lastchecked": None,
        }
        workingdata["user"][interaction.user.id]["apikey"] = api_key
        await interaction.response.send_message(
            "Valid API key. Saving. Do /track next", ephemeral=True
        )
        savedata()
    else:
        await interaction.response.send_message(
            "Invalid API key. Make sure it is the same API key Wingman uses.", ephemeral=True
        )


@bot.tree.command(description="Start tracking bosses")
@app_commands.describe(content_type="The content you want to track")
async def track(
    interaction: discord.Interaction,
    content_type: Literal["fractals", "raids", "raids cm", "strikes", "strikes cm", "golem"],
):
    user = interaction.user.id
    if user not in workingdata["user"].keys():
        await interaction.response.send_message(
            "You are not a registered user. Do /adduser"
        )
        return

    if content_type == "fractals":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user][
            "tracked_boss_ids"
        ].union(fractal_cm_boss_ids)
    elif content_type == "raids":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user][
            "tracked_boss_ids"
        ].union(raid_boss_ids)
    elif content_type == "raids cm":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user][
            "tracked_boss_ids"
        ].union(raid_cm_boss_ids)
    elif content_type == "strikes":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user][
            "tracked_boss_ids"
        ].union(strike_boss_ids)
    elif content_type == "strikes cm":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user][
            "tracked_boss_ids"
        ].union(strike_cm_boss_ids)
    elif content_type == "golem":
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
@app_commands.describe(new_boss_id="Positive new boss id")
@commands.is_owner()
async def addnewbossid(interaction: discord.Interaction, boss_type: Literal["fractals", "raids", "strikes", "golem"], new_boss_id: str):
    # Example boss of each type we search to find channels with each type
    if boss_type == "raids":
        bossid = "19450"
    elif boss_type == "strikes":
        bossid = "22343"
    elif boss_type == "fractals":
        bossid = "-17759"
    elif boss_type == "golem":
        bossid = "16199"
        
    selectsql = f"""SELECT DISTINCT id, type FROM bossserverchannels WHERE boss_id = '{bossid}'"""
    insertsql = """INSERT INTO bossserverchannels VALUES(?,?,?)"""

    cur.execute(selectsql)
    rows = cur.fetchall()
    dpschannelids = [item[0] for item in rows if item[1] == "dps"]
    timechannelids = [item[0] for item in rows if item[1] == "time"]

    for channel_id in dpschannelids:
        cur.execute(insertsql, (channel_id, new_boss_id, "dps"))
    for channel_id in timechannelids:
        cur.execute(insertsql, (channel_id, new_boss_id, "time"))
    con.commit()

    numservers = len(rows)
    print("Added new boss id: " + str(new_boss_id) + " to bosstype: " + str(boss_type))
    await interaction.response.send_message(f"Success! Added boss {numservers} times")


@bot.tree.command(description="Add tracking for when game adds new boss")
@app_commands.describe(new_boss_id="Positive new boss id")
@commands.is_owner()
async def removenewbossid(interaction: discord.Interaction, boss_type: Literal["fractals", "raids", "strikes", "golem"], new_boss_id: str):
    # Example boss of each type we search to find channels with each type
    if boss_type == "raids":
        bossid = "19450"
    elif boss_type == "strikes":
        bossid = "22343"
    elif boss_type == "fractals":
        bossid = "-17759"
    elif boss_type == "golem":
        bossid = "16199"
        
    selectsql = f"""SELECT DISTINCT id, type FROM bossserverchannels WHERE boss_id = '{bossid}'"""
    

    cur.execute(selectsql)
    rows = cur.fetchall()
    dpschannelids = [item[0] for item in rows if item[1] == "dps"]
    timechannelids = [item[0] for item in rows if item[1] == "time"]

    for channel_id in dpschannelids:
        deletesql = """DELETE FROM bossserverchannels WHERE id = ? AND boss_id = ? AND type = ?"""
        cur.execute(deletesql, (channel_id, new_boss_id, "dps"))
    for channel_id in timechannelids:
        deletesql = """DELETE FROM bossserverchannels WHERE id = ? AND boss_id = ? AND type = ?"""
        cur.execute(deletesql, (channel_id, new_boss_id, "time"))
    con.commit()

    numservers = len(rows)
    print("Added new boss id: " + str(new_boss_id) + " to bosstype: " + str(boss_type))
    await interaction.response.send_message(f"Success! Removed boss {numservers} times")

@bot.tree.command(description="Links the about info")
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
    description="In the channel where the command is called, post a message when there is a new patch record"
)
@app_commands.describe(content_type="The content you want to track")
@app_commands.checks.has_permissions(administrator=True)
# @app_commands.checks.bot_has_permissions(send_message=True, embed_links=True, view_channel=True)
@commands.guild_only()
async def channeltrackboss(
    interaction: discord.Interaction,
    ping_type: Literal["dps", "time", "supportdps"],
    content_type: Literal["fractals", "raids", "raids cm", "strikes", "strikes cm", "golem", "all"],
):
    channel_id = interaction.channel_id
    sql = """INSERT INTO bossserverchannels VALUES(?,?,?)"""
    if content_type == "fractals":
        for boss_id in fractal_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, ping_type))
            con.commit()
    elif content_type == "raids":
        for boss_id in raid_boss_ids:
            cur.execute(sql, (channel_id, boss_id, ping_type))
            con.commit()
    elif content_type == "raids cm":
        for boss_id in raid_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, ping_type))
            con.commit()
    elif content_type == "strikes":
        for boss_id in strike_boss_ids:
            cur.execute(sql, (channel_id, boss_id, ping_type))
            con.commit()
    elif content_type == "strikes cm":
        for boss_id in strike_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, ping_type))
            con.commit()
    elif content_type == "all":
        for boss_id in all_boss_ids:
            cur.execute(sql, (channel_id, boss_id, ping_type))
            con.commit()
    elif content_type == "golem":
        if ping_type != "dps":
            await interaction.response.send_message("Only DPS ping_type is supported for golems. Try again.")
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
@app_commands.describe(content_type="The content you want to track")
@app_commands.checks.has_permissions(administrator=True)
@commands.guild_only()
async def channeluntrackboss(
    interaction: discord.Interaction,
    ping_type: Literal["dps", "time", "supportdps"],
    content_type: Literal["fractals", "raids", "raids cm", "strikes", "strikes cm", "golem", "all"],
):
    channel_id = interaction.channel_id
    sql = """DELETE FROM bossserverchannels WHERE id=? AND boss_id=? AND type=?"""
    if content_type == "fractals":
        for boss_id in fractal_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, ping_type))
            con.commit()
    elif content_type == "raids":
        for boss_id in raid_boss_ids:
            cur.execute(sql, (channel_id, boss_id, ping_type))
            con.commit()
    elif content_type == "raids cm":
        for boss_id in raid_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, ping_type))
            con.commit()
    elif content_type == "strikes":
        for boss_id in strike_boss_ids:
            cur.execute(sql, (channel_id, boss_id, ping_type))
            con.commit()
    elif content_type == "strikes cm":
        for boss_id in strike_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, ping_type))
            con.commit()
    elif content_type == "all":
        for boss_id in all_boss_ids + golem_ids:
            cur.execute(sql, (channel_id, boss_id, ping_type))
            con.commit()
    elif content_type == "golem":
        for boss_id in golem_ids:
            cur.execute(sql, (channel_id, boss_id, "dps"))
            con.commit()
    await interaction.response.send_message("Removed bosses from track list.")
    return

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
async def patchdpsrecord(content, cur, leaderboardtype="dps"):
    await bot.wait_until_ready()

    # TODO: check if acctname is in tracked list
    bossid = content["bossID"]

    if leaderboardtype == "supportdps":
        cur.execute(
            "SELECT DISTINCT id FROM bossserverchannels WHERE boss_id=? AND type=?",
            (bossid, "supportdps"),
        )
    elif leaderboardtype == "dps":
        cur.execute(
            "SELECT DISTINCT id FROM bossserverchannels WHERE boss_id=? AND type=?",
            (bossid, "dps"),
        )
    else:
        raise Exception("Invalid leaderboardtype")
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
