import atexit
import importlib
import json
import logging.config
import logging.handlers
import pathlib
import pickle
import sqlite3
import ssl
import urllib.request
from datetime import datetime as dt
from datetime import timezone
from os.path import exists
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import get

import startupvars
from startupvars import *

logger = logging.getLogger(__name__)

ssl._create_default_https_context = ssl._create_unverified_context

description = """A bot to pull personal best and leaderboard info from gw2wingman."""

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="?", description=description, intents=intents)

dbfilename = "data/wingmanbot.db"
if not exists(dbfilename):
    initializedb(dbfilename)


def setup_logging():
    config_file = pathlib.Path("logging_config.json")
    with open(config_file) as f_in:
        config = json.load(f_in)

    logging.config.dictConfig(config)
    queue_handler = logging.getHandlerByName("queue_handler")
    if queue_handler is not None:
        queue_handler.listener.start()
        atexit.register(queue_handler.listener.stop)


def savedata():
    with open("data/workingdata.pkl", "wb") as f:
        pickle.dump(workingdata, f)
    return None


def get_db_connection():
    con = sqlite3.connect(dbfilename)
    cur = con.cursor()
    return con, cur


def execute_sql(sql, params=()):
    con, cur = get_db_connection()
    cur.execute(sql, params)
    con.commit()
    con.close()


def fetch_sql(sql, params=()):
    con, cur = get_db_connection()
    cur.execute(sql, params)
    rows = cur.fetchall()
    con.close()
    return rows


def isapikeyvalid(key):
    with urllib.request.urlopen(
        f"https://gw2wingman.nevermindcreations.de/api/getPlayerStats?apikey={key}"
    ) as url:
        playerstatdump = json.load(url)
    return "error" not in playerstatdump.keys()


def logtimestampfromlink(link):
    format_data = "%Y%m%d-%H%M%S %z"
    # 1 dash is Wingman uploader link format
    if link.count("-") == 1:
        timestamp = f"{link[:15]} -0500"
    elif link.count("-") == 2:
        timestamp = f"{link[5:20]} -0500"
    return dt.strptime(timestamp, format_data)


# Helper function ensures embed bodies are not more than 1024 characters each.
def embed_wrap(bosslinks, stats):  # sourcery skip: simplify-numeric-comparison
    bosslinkresult = []
    statresult = []
    bosslink_string = ""
    stat_string = ""

    for i, s in enumerate(bosslinks):
        # Check if adding the next string would exceed the limit
        if len(bosslink_string) + len(s) + 1 > 1024:
            bosslinkresult.append(bosslink_string)
            statresult.append(stat_string)
            bosslink_string = s  # Start a new string
            stat_string = stats[i]
        elif bosslink_string:
            bosslink_string += "\n" + s
            stat_string += "\n" + stats[i]
        else:
            bosslink_string = s
            stat_string = stats[i]

    # Add the last string if it's not empty
    if bosslink_string:
        bosslinkresult.append(bosslink_string)
        statresult.append(stat_string)

    return bosslinkresult, statresult


@bot.event
async def on_ready():
    global workingdata, aleeva_token
    with open("data/workingdata.pkl", "rb") as f:
        workingdata = pickle.load(f)
    await bot.tree.sync()

    dbfilename = "data/wingmanbot.db"
    if not exists(dbfilename):
        initializedb(dbfilename)

    setup_logging()

    logger.debug(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.debug("------")


@bot.tree.error
async def on_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You must be a server administrator to use this command.", ephemeral=True
        )
    else:
        error = error.original


@bot.tree.command(description="Add a user to be tracked")
@app_commands.describe(api_key="API Key used in Wingman")
async def adduser(interaction: discord.Interaction, api_key: str):
    if not isapikeyvalid(api_key):
        await interaction.response.send_message(
            "Invalid API key. Make sure it is the same API key Wingman uses.",
            ephemeral=True,
        )
        return
    # Remove any old apikeys to ensure theres not multiple for some reason.
    execute_sql(f"""DELETE FROM users WHERE id = '{interaction.user.id}'""")
    insertsql = """INSERT INTO users VALUES(?,?,?,?)"""
    execute_sql(insertsql, (interaction.user.id, api_key, None, None))
    # workingdata["user"][interaction.user.id] = {
    #     "apikey": None,
    #     "tracked_boss_ids": set(),
    #     "lastchecked": None,
    # }
    # workingdata["user"][interaction.user.id]["apikey"] = api_key
    await interaction.response.send_message("Saving API Key.", ephemeral=True)
    # savedata()


@bot.tree.command(description="Start tracking bosses")
@app_commands.describe(content_type="The content you want to track")
async def track(
    interaction: discord.Interaction,
    content_type: Literal[
        "fractals", "raids", "raids cm", "strikes", "strikes cm", "golem"
    ],
):
    user = interaction.user.id
    if user not in workingdata["user"].keys():
        await interaction.response.send_message(
            "You are not a registered user. Do /adduser"
        )
        return

    workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user][
        "tracked_boss_ids"
    ].union(boss_content_lists[content_type])

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
            f"https://gw2wingman.nevermindcreations.de/api/getPlayerStats?apikey={APIKey}"
        ) as url:
            playerstatdump = json.load(url)

        # Look for new top dps log
        topstats = playerstatdump["topPerformances"][mostrecentpatchid]
        bossescleared = list(set(tracked_boss_ids).intersection(topstats.keys()))
        responses = []
        for boss in bossescleared:
            # Remove negative from id if present so we can pull boss name from api
            boss_id = boss[1:] if boss.startswith("-") else boss
            specscleared = list(set(topstats[boss].keys()).intersection(professions))
            for spec in specscleared:
                logtimestamp = logtimestampfromlink(topstats[boss][spec]["link"])
                # Check if log timestamps are from after last check
                if logtimestamp > workingdata["user"][userid]["lastchecked"]:
                    responses.append(
                        f'New best DPS log on {bossdump[boss_id]["name"]}!\nSpec: {spec}\nDPS: {topstats[boss][spec]["topDPS"]}\nLink: https://gw2wingman.nevermindcreations.de/log/{topstats[boss][spec]["link"]}'
                    )

        # Look for new fastest log
        toptimes = playerstatdump["topBossTimes"][mostrecentpatchid]
        bossescleared = list(set(tracked_boss_ids).intersection(toptimes.keys()))
        for boss in bossescleared:
            # Remove negative from id if present so we can pull boss name from api
            boss_id = boss[1:] if boss.startswith("-") else boss
            logtimestamp = logtimestampfromlink(toptimes[boss]["link"])
            if logtimestamp > workingdata["user"][userid]["lastchecked"]:
                bosstime = dt.fromtimestamp(
                    toptimes[boss]["durationMS"] / 1000.0
                ).strftime("%M:%S.%f")[:-3]
                responses.append(
                    f'New fastest log on {bossdump[boss_id]["name"]}!\nTime: {bosstime}\nLink: https://gw2wingman.nevermindcreations.de/log/{toptimes[boss]["link"]}'
                )

        if not responses:
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
            "Error. You need to add your api key first. Do /adduser"
        )
    else:
        await interaction.response.send_message(
            "Error. You don't have any tracked bosses. Do /track"
        )


@bot.tree.command(description="Add tracking for when game adds new boss")
@app_commands.describe(new_boss_id="Positive new boss id")
@commands.is_owner()
async def addnewbossid(
    interaction: discord.Interaction,
    boss_type: Literal["fractals", "raids", "strikes", "golem"],
    new_boss_id: str,
):
    # Example boss of each type we search to find channels with each type
    bossid = example_boss_ids[boss_type]

    rows = fetch_sql(
        f"""SELECT DISTINCT id, type FROM bossserverchannels WHERE boss_id = '{bossid}'"""
    )
    channel_ids = {
        "dps": [item[0] for item in rows if item[1] == "dps"],
        "supportdps": [item[0] for item in rows if item[1] == "supportdps"],
        "time": [item[0] for item in rows if item[1] == "time"],
    }

    insertsql = """INSERT INTO bossserverchannels VALUES(?,?,?)"""
    for channel_type, ids in channel_ids.items():
        for channel_id in ids:
            execute_sql(insertsql, (channel_id, new_boss_id, channel_type))

    logger.info(f"Added new boss id: {new_boss_id} to bosstype: {str(boss_type)}")
    await interaction.response.send_message(f"Success! Added boss {len(rows)} times")


@bot.tree.command(description="Add tracking for when game adds new boss")
@app_commands.describe(new_boss_id="Positive new boss id")
@commands.is_owner()
async def removenewbossid(
    interaction: discord.Interaction,
    boss_type: Literal["fractals", "raids", "strikes", "golem"],
    new_boss_id: str,
):
    # Example boss of each type we search to find channels with each type
    bossid = example_boss_ids[boss_type]

    rows = fetch_sql(
        f"""SELECT DISTINCT id, type FROM bossserverchannels WHERE boss_id = '{bossid}'"""
    )
    channel_ids = {
        "dps": [item[0] for item in rows if item[1] == "dps"],
        "supportdps": [item[0] for item in rows if item[1] == "supportdps"],
        "time": [item[0] for item in rows if item[1] == "time"],
    }

    deletesql = (
        """DELETE FROM bossserverchannels WHERE id = ? AND boss_id = ? AND type = ?"""
    )
    for channel_type, ids in channel_ids.items():
        for channel_id in ids:
            execute_sql(deletesql, (channel_id, new_boss_id, channel_type))

    logger.info(f"Removed boss id: {new_boss_id} to bosstype: {boss_type}")
    await interaction.response.send_message(f"Success! Removed boss {len(rows)} times")


@bot.tree.command(description="What the heck is going on")
@commands.is_owner()
async def debugchannels(interaction: discord.Interaction):
    rows = fetch_sql("""SELECT DISTINCT id, type FROM bossserverchannels""")
    dpschannelids = [item[0] for item in rows if item[1] == "dps"]
    timechannelids = [item[0] for item in rows if item[1] == "time"]
    supportdpschannelids = [item[0] for item in rows if item[1] == "supportdps"]
    channel_ids = list(set(dpschannelids + timechannelids + supportdpschannelids))

    for channel_id in channel_ids:
        channel = bot.get_channel(channel_id)
        logger.debug(channel_id)
        try:
            logger.debug(channel.guild.unavailable)
            logger.debug(channel.guild.name)
            logger.debug(channel.guild.owner.name)
        except Exception as err:
            logger.debug("Guild info did not work")
            logger.error(err)
            continue
    await interaction.response.send_message("Results sent to log.")


@bot.tree.command(description="Remove channel_id from database")
@commands.is_owner()
async def prune_channel(interaction: discord.Interaction, channel_id: str):
    logger.info(f"Removing channel: {channel_id}")
    execute_sql("""DELETE FROM bossserverchannels WHERE id = ?""", (channel_id))
    await interaction.response.send_message("Success!")


def construct_bossnamelinks_and_stats(id, patch_id, playerstatdump, leaderboard, spec):
    if id.startswith("-"):
        bossname = f"{bossidtoname[id[1:]]} CM"
    else:
        bossname = bossidtoname[id]

    if leaderboard == "time":
        link = f"https://gw2wingman.nevermindcreations.de/log/{playerstatdump['topBossTimes'][patch_id][id]['link']}"
        stat = dt.fromtimestamp(
            playerstatdump["topBossTimes"][patch_id][id]["durationMS"] / 1000
        ).strftime("%M:%S.%f")[:-3]
    elif leaderboard == "dps":
        link = f"https://gw2wingman.nevermindcreations.de/log/{playerstatdump['topPerformances'][patch_id][id][spec]['link']}"
        stat = str(playerstatdump["topPerformances"][patch_id][id][spec]["topDPS"])
    elif leaderboard == "supportdps":
        link = f"https://gw2wingman.nevermindcreations.de/log/{playerstatdump['topPerformancesSupport'][patch_id][id][spec]['link']}"
        stat = str(
            playerstatdump["topPerformancesSupport"][patch_id][id][spec]["topDPS"]
        )

    return f"[{bossname}]({link})", stat


@bot.tree.command(description="Flex on your friends by sharing your best logs.")
@app_commands.describe(
    leaderboard="Which type of leaderboard you would like to show.",
    patch_id="Optional - Patch ID, by default will show the latest. Patch IDs are generally 'YY-MM'",
    content="Optional - The bosses you would like to show organized by content type. Defaults to all. Includes normal and CMs.",
    spec="Optional - The specialization you want to show. Defaults to overall which includes all specs. Cannot be used with time leaderboard",
)
async def flex(
    interaction: discord.Interaction,
    leaderboard: Literal["time", "dps", "support"],
    patch_id: Optional[str] = "latest",
    content: Optional[Literal["raids", "fractals", "strikes", "all"]] = "all",
    spec: Optional[str] = "overall",
):
    await interaction.response.defer(thinking=True)
    # Check for apikey and retrieve data
    userid = interaction.user.id
    rows = fetch_sql(f"""SELECT DISTINCT apikey FROM users WHERE id = '{userid}'""")
    if rows == [] or len(rows) > 1:
        await interaction.followup.send("API-Key Error. Do /adduser with your API-key")
        return
    if spec != "overall" and leaderboard == "time":
        await interaction.followup.send(
            "Error. Currently do not support time leaderboard filtered by specialization. Try again without specifying the specialization."
        )
        return
    apikey = rows[0][0]
    logger.debug("Found API key {apikey}")

    with urllib.request.urlopen(
        f"https://gw2wingman.nevermindcreations.de/api/getPlayerStats?apikey={apikey}"
    ) as url:
        playerstatdump = json.load(url)

    # Handle the command arguments
    if patch_id == "latest":
        patch_id = list(playerstatdump["topBossTimes"].keys())[-2]

    bossescompleted = set(playerstatdump["topBossTimes"][patch_id].keys())
    bossestocheck = boss_content_sets[content]

    # Intersection of bosses completed and bosses being checked
    boss_ids = bossescompleted & bossestocheck
    if not boss_ids:
        await interaction.followup.send("Did not find any logs for your settings.")
        return

    # Create the embed
    accountname = playerstatdump["account"]
    embed = discord.Embed(
        title=f"{accountname}'s best {leaderboard} logs",
        description=f"For the {patch_id} patch in {content} on {spec}",
    )

    bossnamelinks = []
    stats = []
    # Construct embed based on the data and arguments
    for id in boss_ids:
        if (
            leaderboard == "support"
            and playerstatdump["topPerformancesSupport"][patch_id][id][spec]["topDPS"]
            == 0
        ):
            continue
        if spec in playerstatdump["topPerformances"][patch_id][id]:
            bossnamelink, stat = construct_bossnamelinks_and_stats(
                id, patch_id, playerstatdump, leaderboard, spec
            )
            bossnamelinks.append(bossnamelink)
            stats.append(stat)

    if leaderboard == "support" and not bossnamelinks:
        await interaction.followup.send(
            "Did not find any support logs for your settings."
        )
        return

    titletext = {"dps": "DPS", "support": "Support DPS", "time": "Time"}
    bossnamebody, statbody = embed_wrap(bossnamelinks, stats)
    for i, body in enumerate(bossnamebody):
        embed.add_field(name="Boss", value=body, inline=True)
        embed.add_field(
            name=f"{titletext[leaderboard]}", value=statbody[i], inline=True
        )
        embed.add_field(name=" ", value=" ")
    await interaction.followup.send(embed=embed)


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
    content_type: Literal[
        "fractals", "raids", "raids cm", "strikes", "strikes cm", "golem", "all"
    ],
):
    if content_type == "golem" and ping_type != "dps":
        await interaction.response.send_message(
            "Only DPS ping type is supported for golems. Try again."
        )
        return

    await interaction.response.defer(thinking=True)

    sql = """INSERT INTO bossserverchannels VALUES(?,?,?)"""
    for boss_id in boss_content_lists[content_type]:
        execute_sql(sql, (interaction.channel_id, boss_id, ping_type))

    await interaction.followup.send(
        "Added bosses to track list. Will post in this channel when the next patch record is posted"
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
    content_type: Literal[
        "fractals", "raids", "raids cm", "strikes", "strikes cm", "golem", "all"
    ],
):
    await interaction.response.defer(thinking=True)

    sql = """DELETE FROM bossserverchannels WHERE id=? AND boss_id=? AND type=?"""
    for boss_id in boss_content_lists[content_type]:
        execute_sql(sql, (interaction.channel_id, boss_id, ping_type))

    await interaction.followup.send("Removed bosses from track list.")
    return


@bot.event
async def pingreportedlog(content):
    await bot.wait_until_ready()
    loglink = content["link"]
    reasontext = content["reason"]
    bossid = content["bossID"]
    bossname = content["bossName"]
    time = content["duration"]
    reportedlogchannel = 852681966444740620

    log = discord.Embed(
        title=f"Log reported on {bossname}, reason: {reasontext}",
        url=f"https://gw2wingman.nevermindcreations.de/log/{loglink}",
    )
    if bossid.startswith("-"):
        bossid = bossid[1:]
    iconurl = f"https://gw2wingman.nevermindcreations.de{bossdump[bossid]['icon']}"
    log.set_thumbnail(url=iconurl)
    log.add_field(name="Time", value=time, inline=True)
    log.add_field(name="Link", value=loglink, inline=True)

    channel = bot.get_channel(reportedlogchannel)
    try:
        bot.loop.create_task(channel.send(embed=log))
    except Exception as err:
        logger.error("Reported long could not be pinged")
        logger.error(err)
    logger.debug(f"Log reported {loglink}, reason: {reasontext}")


@bot.event
async def internalmessage(content):
    # Echos any message sent to the /internalmessage/ endpoint to the internal botspam channel
    await bot.wait_until_ready()
    message = content["message"]
    internalmessagechannel = 1208602365972717628

    channel = bot.get_channel(internalmessagechannel)
    try:
        bot.loop.create_task(channel.send(content=message))
    except Exception as err:
        logger.error("Internal message could not be sent")
        logger.error(err)

    logger.debug(f"Internal message {message}")


def determine_era(content, patchidlist):
    if content["eraID"] == "all":
        return "All Time"
    elif content["eraID"] not in patchidlist:
        importlib.reload(startupvars)
        return "Current Patch"
    elif content["eraID"] == patchidlist[0]:
        return "Current Patch"
    else:
        logger.debug("Record for old patch, ignoring")
        return None


def construct_embed(title, url, groups, iconurl, fields):
    log = discord.Embed(title=title, url=url)
    if groups:
        log.add_field(name="Group", value=groups, inline=False)
    log.set_thumbnail(url=iconurl)
    for name, value, inline in fields:
        log.add_field(name=name, value=value, inline=inline)
    return log


def get_icon_url(content, bossid, bossdump):
    iconurl = content["groupIcons"][0]
    if (
        iconurl
        == "https://gw2wingman.nevermindcreations.de/static/groupIcons/defGroup.png"
    ):
        if bossid.startswith("-"):
            bossid = bossid[1:]
        iconurl = f"https://gw2wingman.nevermindcreations.de{bossdump[bossid]['icon']}"
    return iconurl


@bot.event
async def patchtimerecord(content):
    await bot.wait_until_ready()
    bossid = content["bossID"]
    rows = fetch_sql(
        "SELECT DISTINCT id FROM bossserverchannels WHERE boss_id=? AND type=?",
        (bossid, "time"),
    )

    if not rows:
        logger.debug("Nobody wanted this ping")
        return

    bossname = bossname_from_id(content, bossid)
    era = determine_era(content, patchidlist)
    if era is None:
        return

    players = content["players_chars"]
    accts = content["players"]
    groups = ", ".join(content["group"])
    time = dt.fromtimestamp(content["duration"] / 1000).strftime("%M:%S.%f")[:-3]
    prevtime = dt.fromtimestamp(content["previousDuration"] / 1000).strftime(
        "%M:%S.%f"
    )[:-3]
    loglink = content["link"]
    isLowman = bool(content["isLowman"])
    prevPlayerCount = content["previousPlayerAmount"]

    iconurl = get_icon_url(content, bossid, bossdump)
    emoji_list = [
        str(get(bot.emojis, name=spec)) for spec in content["players_professions"]
    ]
    playerscontent = "\n".join(
        f"{m} {n}/{o}" for m, n, o in zip(emoji_list, players, accts)
    )

    fields = [
        ("Time", time, True),
        ("Previous Time", prevtime, True),
        ("Era", era, True),
        ("Players", playerscontent, False),
    ]
    title = f"New fastest log on {bossname}"
    if isLowman:
        fields = [
            ("Time", time, True),
            ("Previous Time", prevtime, True),
            ("Previous Player Count", prevPlayerCount, True),
            ("Era", era, True),
            ("Players", playerscontent, False),
        ]
        title = f"New best lowman log on {bossname}"
    log = construct_embed(
        title,
        f"https://gw2wingman.nevermindcreations.de/log/{loglink}",
        groups,
        iconurl,
        fields,
    )

    send_records(rows, log)


def send_records(rows, log):
    for row in rows:
        channel = bot.get_channel(row[0])
        if channel is None:
            continue
        try:
            bot.loop.create_task(channel.send(embed=log))
        except Exception as err:
            logger.error(f"Failed to write to channel: {str(channel.id)}")
            logger.error(err)


@bot.event
async def patchdpsrecord(content, leaderboardtype="dps"):
    await bot.wait_until_ready()
    bossid = content["bossID"]
    rows = fetch_sql(
        "SELECT DISTINCT id FROM bossserverchannels WHERE boss_id=? AND type=?",
        (bossid, leaderboardtype),
    )

    # Dont keep going if no channel wants the ping
    if not rows:
        logger.debug("Nobody wanted this ping")
        return

    bossname = bossname_from_id(content, bossid)
    era = determine_era(content, patchidlist)
    if era is None:
        return

    charname = content["character"]
    profession = content["profession"]
    dps = content["dps"]
    dpsdiff = dps - content["previousDps"]
    dpsstring = f"{str(dps)} (+{dpsdiff})"
    acctname = content["account"]

    groups = ", ".join(content["group"])
    loglink = content["link"]
    titletext = {"dps": "DPS", "supportdps": "Support DPS"}
    iconurl = get_icon_url(content, bossid, bossdump)

    emoji = get(bot.emojis, name=profession)
    playercontent = f"{str(emoji)} {charname}/{acctname}"

    fields = [
        (titletext[leaderboardtype], dpsstring, True),
        ("Era", era, True),
        ("Player", playercontent, False),
    ]
    log = construct_embed(
        f"New {titletext[leaderboardtype]} record log on {bossname}",
        f"https://gw2wingman.nevermindcreations.de/log/{loglink}",
        groups,
        iconurl,
        fields,
    )

    send_records(rows, log)


def bossname_from_id(content, bossid):
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
    return bossname


with open("data/discord_token.txt") as f:
    token = f.readline()


def run_discord_bot():
    bot.run(token)
