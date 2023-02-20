import json
import pickle
import ssl
import urllib.request
from datetime import datetime as dt
from datetime import timezone
from typing import Literal
from os.path import exists

import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.utils import get
import sqlite3

from startupvars import *

ssl._create_default_https_context = ssl._create_unverified_context


description = '''A bot to pull personal best and leaderboard info from gw2wingman.'''

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix='?',
                   description=description, intents=intents)


def savedata():
    with open('data/workingdata.pkl', 'wb') as f:
        pickle.dump(workingdata, f)
    return None


def isapikeyvalid(key):
    with urllib.request.urlopen("https://gw2wingman.nevermindcreations.de/api/getPlayerStats?apikey={}".format(key)) as url:
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
    global workingdata
    with open('data/workingdata.pkl', 'rb') as f:
        workingdata = pickle.load(f)
    await bot.tree.sync()
    dbfilename = "data/wingmanbot.db"
    if not exists(dbfilename):
        initializedb(dbfilename)
    global con
    con = sqlite3.connect(dbfilename)
    global cur
    cur = con.cursor()
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')
    # my_task.start()


@bot.tree.error
async def on_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You must be a server administrator to use this command.", ephemeral=True)


# # The following command associates the ID of the guild to that of the channel in which this command is run.
# @bot.command(description="Tell the bot where you want it to put updates")
# async def channel(ctx):
#     guild_id = ctx.guild.id
#     channel_id = ctx.channel.id
#     main_channels[guild_id] = {"channel": channel_id}
#     with open('bot_channels.pkl', 'wb') as f:
#         pickle.dump(main_channels, f)


@bot.tree.command(description="Add a user to be tracked")
@app_commands.describe(apikey="API Key used in Wingman")
async def adduser(interaction: discord.Interaction, apikey: str):
    if isapikeyvalid(apikey):
        workingdata["user"][interaction.user.id] = {
            "apikey": None,
            "tracked_boss_ids": set(),
            "lastchecked": None
        }
        workingdata["user"][interaction.user.id]["apikey"] = apikey
        await interaction.response.send_message("Valid API key. Saving. Do /track next", ephemeral=True)
        savedata()
    else:
        await interaction.response.send_message("Invalid API key try again.", ephemeral=True)


@bot.tree.command(description="Start tracking bosses")
@app_commands.describe(choice="The content you want to track")
async def track(interaction: discord.Interaction, choice: Literal["fractals", "raids", "raids cm", "strikes", "strikes cm"]):
    user = interaction.user.id
    if user not in workingdata["user"].keys():
        await interaction.response.send_message("You are not a registered user. Do /adduser")
        return

    if choice == "fractals":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user]["tracked_boss_ids"].union(
            fractal_cm_boss_ids)
    elif choice == "raids":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user]["tracked_boss_ids"].union(
            raid_boss_ids)
    elif choice == "raids cm":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user]["tracked_boss_ids"].union(
            raid_cm_boss_ids)
    elif choice == "strikes":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user]["tracked_boss_ids"].union(
            strike_boss_ids)
    elif choice == "strikes cm":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user]["tracked_boss_ids"].union(
            strike_cm_boss_ids)
    await interaction.response.send_message("Added bosses to track list. Next /check will not give PBs to reduce spam.", ephemeral=True)
    # Dont spam next time they do /check
    workingdata["user"][user]["lastchecked"] = None
    savedata()


@bot.tree.command(description="Manually check for new PBs")
# @app_commands.describe()
async def check(interaction: discord.Interaction):
    userid = interaction.user.id
    responses = []
    if workingdata["user"][userid]["apikey"] is not None and workingdata["user"][userid]["tracked_boss_ids"] != set():
        APIKey = workingdata["user"][userid]["apikey"]
        tracked_boss_ids = workingdata["user"][userid]["tracked_boss_ids"]

        # Don't link logs if lastchecked is none or before most recent patch
        if workingdata["user"][userid]["lastchecked"] is None or workingdata["user"][userid]["lastchecked"] < mostrecentpatchstartdt:
            await interaction.response.send_message(
                "You haven't checked logs yet this patch. Not linking PBs to reduce spam. Next time /check will link all PB logs", ephemeral=True)
            workingdata["user"][userid]["lastchecked"] = dt.now(
                timezone.utc)  # Update last checked
            savedata()
            return

        with urllib.request.urlopen("https://gw2wingman.nevermindcreations.de/api/getPlayerStats?apikey={}".format(APIKey)) as url:
            playerstatdump = json.load(url)

        # Look for new top dps log
        topstats = playerstatdump["topPerformances"][mostrecentpatchid]
        bossescleared = list(
            set(tracked_boss_ids).intersection(topstats.keys()))
        for boss in bossescleared:
            # Remove negative from id if present so we can pull boss name from api
            if boss.startswith("-"):
                boss_id = boss[1:]
            else:
                boss_id = boss
            specscleared = list(
                set(topstats[boss].keys()).intersection(professions))
            for spec in specscleared:
                logtimestamp = logtimestampfromlink(
                    topstats[boss][spec]["link"])
                # Check if log timestamps are from after last check
                if logtimestamp > workingdata["user"][userid]["lastchecked"]:
                    responses.append("New best DPS log on {}!\nSpec: {}\nDPS: {}\nLink: https://gw2wingman.nevermindcreations.de/log/{}".format(
                        bossdump[boss_id]["name"], spec, topstats[boss][spec]["topDPS"], topstats[boss][spec]["link"]))

        # Look for new fastest log
        toptimes = playerstatdump["topBossTimes"][mostrecentpatchid]
        bossescleared = list(
            set(tracked_boss_ids).intersection(toptimes.keys()))
        for boss in bossescleared:
            # Remove negative from id if present so we can pull boss name from api
            if boss.startswith("-"):
                boss_id = boss[1:]
            else:
                boss_id = boss
            logtimestamp = logtimestampfromlink(toptimes[boss]["link"])
            if logtimestamp > workingdata["user"][userid]["lastchecked"]:
                bosstime = dt.fromtimestamp(
                    toptimes[boss]["durationMS"]/1000.0).strftime('%M:%S.%f')[:-3]
                responses.append("New fastest log on {}!\nTime: {}\nLink: https://gw2wingman.nevermindcreations.de/log/{}".format(
                    bossdump[boss_id]["name"], bosstime, toptimes[boss]["link"]))

        if responses == []:
            await interaction.response.send_message("No new PBs")
        else:
            await interaction.response.defer()
            for response in responses:
                await interaction.followup.send(response)

        workingdata["user"][userid]["lastchecked"] = dt.now(
            timezone.utc)  # Update last checked
        savedata()
    elif workingdata["user"][userid]["apikey"] is None:
        await interaction.response.send_message("Error. You need to add your api key first. Do /useradd")
    else:
        await interaction.response.send_message("Error. You don't have any tracked bosses. Do /track")


@bot.tree.command(description="Debug command to reset last checked to most recent patch day")
# @app_commands.describe()
async def resetlastchecked(interaction: discord.Interaction):
    userid = interaction.user.id
    if userid not in workingdata["user"].keys():
        await interaction.response.send_message("You are not a registered user. Do /adduser", ephemeral=True)
        return

    workingdata["user"][userid]["lastchecked"] = None
    await interaction.response.send_message("Last checked reset to most recent patch day", ephemeral=True)


@bot.tree.command(description="Responds with the last time PBs were checked")
# @app_commands.describe()
async def lastchecked(interaction: discord.Interaction):
    userid = interaction.user.id
    if userid not in workingdata["user"].keys():
        await interaction.response.send_message("You are not a registered user. Do /adduser", ephemeral=True)
        return
    if workingdata["user"][userid]["lastchecked"] is None:
        await interaction.response.send_message("You have never checked logs before.", ephemeral=True)
        return

    lastchecked = workingdata["user"][userid]["lastchecked"]
    delta = dt.now(timezone.utc) - lastchecked
    days, remainder = divmod(delta.total_seconds(), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    await interaction.response.send_message("Last checked " + f"{int(days)} days, {int(hours)} hours, {int(minutes)} minutes" + " ago", ephemeral=True)


@bot.tree.command(description="Link about info")
async def about(interaction: discord.Interaction):
    embed = discord.Embed(title="View github",
                          url="https://github.com/SuperClicheUsername/GW2WingmanPBBot")
    await interaction.response.send_message("Discord bot to help track personal bests and patch records from GW2Wingman. Contact: Yukino Y#0865.", embed=embed)


@bot.tree.command(description="Track bosses to be automatically pinged in channel where command is called on new patch record")
@app_commands.describe(choice="The content you want to track")
@app_commands.checks.has_permissions(administrator=True)
@commands.guild_only()
async def channeltrackboss(interaction: discord.Interaction, pingtype: Literal["dps", "time"], choice: Literal["fractals", "raids", "raids cm", "strikes", "strikes cm"]):
    channel_id = interaction.channel_id
    if choice == "fractals":
        sql = """INSERT INTO bossserverchannels(id, boss_id, type)
                VALUES(?,?,?)"""
        for boss_id in fractal_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
    elif choice == "raids":
        sql = """INSERT INTO bossserverchannels(id, boss_id)
                VALUES(?,?)"""
        for boss_id in raid_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
    elif choice == "raids cm":
        sql = """INSERT INTO bossserverchannels(id, boss_id)
                VALUES(?,?)"""
        for boss_id in raid_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
    elif choice == "strikes":
        sql = """INSERT INTO bossserverchannels(id, boss_id)
                VALUES(?,?)"""
        for boss_id in strike_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
    elif choice == "strikes cm":
        sql = """INSERT INTO bossserverchannels(id, boss_id)
                VALUES(?,?)"""
        for boss_id in strike_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
    await interaction.response.send_message("Added bosses to track list. Will ping channel when next patch record is posted", ephemeral=True)
    con.commit()


@bot.tree.command(description="Untrack bosses from automatic ping list when a new patch record is added")
@app_commands.describe(choice="The content you want to track")
@app_commands.checks.has_permissions(administrator=True)
@commands.guild_only()
async def channeluntrackboss(interaction: discord.Interaction, pingtype: Literal["dps", "time"], choice: Literal["fractals", "raids", "raids cm", "strikes", "strikes cm"]):
    channel_id = interaction.channel_id
    if choice == "fractals":
        sql = """DELETE FROM bossserverchannels
                WHERE id = (channel_id) AND boss_id = (boss_id) AND type = (pingtype)
                VALUES(?,?,?)"""
        for boss_id in fractal_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
    elif choice == "raids":
        sql = """DELETE FROM bossserverchannels
                WHERE id = (channel_id) AND boss_id = (boss_id)
                VALUES(?,?)"""
        for boss_id in raid_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
    elif choice == "raids cm":
        sql = """DELETE FROM bossserverchannels
                WHERE id = (channel_id) AND boss_id = (boss_id)
                VALUES(?,?)"""
        for boss_id in raid_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
    elif choice == "strikes":
        sql = """DELETE FROM bossserverchannels
                WHERE id = (channel_id) AND boss_id = (boss_id)
                VALUES(?,?)"""
        for boss_id in strike_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
    elif choice == "strikes cm":
        sql = """DELETE FROM bossserverchannels
                WHERE id = (channel_id) AND boss_id = (boss_id)
                VALUES(?,?)"""
        for boss_id in strike_cm_boss_ids:
            cur.execute(sql, (channel_id, boss_id, pingtype))
    await interaction.response.send_message("Removed bosses from track list.", ephemeral=True)
    con.commit()


# @bot.event
# async def personaldps(content):
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
# async def personaltime(content):
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
async def patchtimerecord(content):
    await bot.wait_until_ready()
    if not cur:
        dbfilename = "data/wingmanbot.db"
        con = sqlite3.connect(dbfilename)
        cur = con.cursor()
    # TODO: check if acctname is in tracked list
    bossid = content["bossID"]
    cur.execute(
        "SELECT id FROM bossserverchannels WHERE boss_id=? AND type=?", (bossid, "time"))
    rows = cur.fetchall()

    # Dont keep going if no channel wants the ping
    if not rows:
        print("Nobody wanted this ping")
        return

    bossname = content["bossName"]
    era = "Current Patch"
    if content["eraID"] == "all":
        era = "All Time"
    # TODO: check if bossid is in tracked list

    # Construct message from POSTed content

    players = content["players_chars"]
    groups = ", ".join(content["group"])
    time = dt.fromtimestamp(content["duration"]/1000).strftime('%M:%S.%f')[:-3]
    prevtime = dt.fromtimestamp(
        content["previousDuration"]/1000).strftime('%M:%S.%f')[:-3]
    loglink = content["link"]

    log = discord.Embed(
        title="New fastest log on {}".format(bossname), url="https://gw2wingman.nevermindcreations.de/log/" + loglink)
    if groups:
        log.add_field(name="Group", value=groups, inline=False)
        iconurl = content["groupIcons"][0]

        # If no group icon get boss icon
        if iconurl == "https://gw2wingman.nevermindcreations.de/static/groupIcons/defGroup.png":
            if bossid.startswith("-"):
                bossid = bossid[1:]
            iconurl = "https://gw2wingman.nevermindcreations.de" + \
                bossdump[bossid]["icon"]
        log.set_thumbnail(url=iconurl)
    else:
        if bossid.startswith("-"):
            bossid = bossid[1:]
        iconurl = "https://gw2wingman.nevermindcreations.de" + \
            bossdump[bossid]["icon"]
        log.set_thumbnail(url=iconurl)

    log.add_field(name="Time", value=time, inline=True)
    log.add_field(name="Previous Time", value=prevtime, inline=True)
    log.add_field(name="Era", value=era, inline=True)

    # TODO: Almost certainly breaks if emojis aren't available. add checks
    emoji_list = []
    for spec in content["players_professions"]:
        emoji = get(bot.emojis, name=spec)
        emoji_list.append(str(emoji))
    playerscontent = [m + " " + n for m, n in zip(emoji_list, players)]
    playerscontent = "\n".join(playerscontent)

    log.add_field(name="Players", value=playerscontent)

    # Distribute message

    for row in rows:
        channel = bot.get_channel(row[0])
        bot.loop.create_task(channel.send(embed=log))


@bot.event
async def patchdpsrecord(content):
    await bot.wait_until_ready()
    if not cur:
        dbfilename = "data/wingmanbot.db"
        con = sqlite3.connect(dbfilename)
        cur = con.cursor()
        
    # TODO: check if acctname is in tracked list
    bossid = content["bossID"]
    cur.execute(
        "SELECT id FROM bossserverchannels WHERE boss_id=? AND type=?", (bossid, "dps"))
    rows = cur.fetchall()

    # Dont keep going if no channel wants the ping
    if not rows:
        print("Nobody wanted this ping")
        return

    bossname = content["bossName"]
    era = "Current Patch"
    if content["eraID"] == "all":
        era = "All Time"
    charname = content["character"]
    profession = content["profession"]
    dps = content["dps"]
    prevdps = content["previousDps"]
    acctname = content["account"]
    # TODO: check if bossid is in tracked list

    # Construct message from POSTed content
    groups = ", ".join(content["group"])
    loglink = content["link"]

    log = discord.Embed(
        title="New DPS record log on {}".format(bossname), url="https://gw2wingman.nevermindcreations.de/log/" + loglink)
    if groups:
        log.add_field(name="Group", value=groups, inline=False)
        iconurl = content["groupIcons"][0]

        # If no group icon get boss icon
        if iconurl == "https://gw2wingman.nevermindcreations.de/static/groupIcons/defGroup.png":
            if bossid.startswith("-"):
                bossid = bossid[1:]
            iconurl = "https://gw2wingman.nevermindcreations.de" + \
                bossdump[bossid]["icon"]
        log.set_thumbnail(url=iconurl)
    else:
        if bossid.startswith("-"):
            bossid = bossid[1:]
        iconurl = "https://gw2wingman.nevermindcreations.de" + \
            bossdump[bossid]["icon"]
        log.set_thumbnail(url=iconurl)

    log.add_field(name="DPS", value=dps, inline=True)
    log.add_field(name="Previous DPS", value=prevdps, inline=True)
    log.add_field(name="Era", value=era, inline=True)

    # TODO: Almost certainly breaks if emojis aren't available. add checks
    emoji = get(bot.emojis, name=profession)
    playercontent = str(emoji) + " " + charname + "/" + acctname

    log.add_field(name="Player", value=playercontent)

    # Distribute message
    for row in rows:
        channel = bot.get_channel(row[0])
        bot.loop.create_task(channel.send(embed=log))
    # channel = bot.get_channel(1070109613355192370)
    # Wingman discord bot channel
    # channel = bot.get_channel(1070495636744568914)
    # bot.loop.create_task(channel.send(embed=log))

with open('data/discord_token.txt') as f:
    token = f.readline()


def run_discord_bot():
    bot.run(token)
