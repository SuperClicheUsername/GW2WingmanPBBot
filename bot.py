import importlib
import json
import logging
import logging.config
import pathlib
import pickle
import sqlite3
import ssl
import urllib
import urllib.request
from datetime import UTC
from datetime import datetime as dt
from os.path import exists
from typing import Literal
from urllib.parse import quote as urlquote

import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import get

import startupvars
from startupvars import (
    boss_content_lists,
    boss_content_sets,
    bossdump,
    bossidtoname,
    example_boss_ids,
    initializedb,
    mostrecentpatchid,
    mostrecentpatchstartdt,
    patchidlist,
    professions,
)

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


def setup_logging() -> None:
    config_file = pathlib.Path("logging_config.json")
    with open(config_file) as f_in:
        config = json.load(f_in)

    logging.config.dictConfig(config)


def savedata() -> None:
    with open("data/workingdata.pkl", "wb") as f:
        pickle.dump(workingdata, f)


def get_db_connection() -> tuple[sqlite3.Connection, sqlite3.Cursor]:
    con = sqlite3.connect(dbfilename)
    cur = con.cursor()
    return con, cur


def execute_sql(sql: str, params=()) -> None:  # noqa: ANN001
    con, cur = get_db_connection()
    cur.execute(sql, params)
    con.commit()
    con.close()


def fetch_sql(sql: str, params=()) -> list:  # noqa: ANN001
    con, cur = get_db_connection()
    cur.execute(sql, params)
    rows = cur.fetchall()
    con.close()
    return rows


def isapikeyvalid(key: str) -> bool:
    with urllib.request.urlopen(
        f"https://gw2wingman.nevermindcreations.de/api/getPlayerStats?apikey={key}",
    ) as url:
        playerstatdump = json.load(url)
    return "error" not in playerstatdump


def logtimestampfromlink(link: str) -> dt:
    format_data = "%Y%m%d-%H%M%S %z"
    # 1 dash is Wingman uploader link format
    if link.count("-") == 1:
        timestamp = f"{link[:15]} -0500"
    # 2 dashes is dps.report conversion format
    elif link.count("-") == 2:  # noqa: PLR2004
        timestamp = f"{link[5:20]} -0500"
    else:
        logger.error(f"Could not figure out timestamp from link: {link}")
        raise ValueError
    return dt.strptime(timestamp, format_data)


# Helper function ensures embed bodies are not more than 1024 characters each.
def embed_wrap(
    bosslinks: list[str],
    stats: list[str],
) -> tuple[list, list]:  # sourcery skip: simplify-numeric-comparison
    bosslinkresult = []
    statresult = []
    bosslink_string = ""
    stat_string = ""
    MAX_LINE_LENGTH = 1024  # noqa: N806

    for i, s in enumerate(bosslinks):
        # Check if adding the next string would exceed the limit
        if len(bosslink_string) + len(s) + 1 > MAX_LINE_LENGTH:
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
async def on_ready() -> None:
    global workingdata, aleeva_token  # noqa: PLW0602, PLW0603
    with open("data/workingdata.pkl", "rb") as f:
        workingdata = pickle.load(f)
    await bot.tree.sync()

    dbfilename = "data/wingmanbot.db"
    if not exists(dbfilename):
        initializedb(dbfilename)

    setup_logging()

    if bot.user is not None:
        logger.debug(f"Logged in as {bot.user} (ID: {bot.user.id})")
        logger.debug("------")


@bot.tree.error
async def on_command_error(
    interaction: discord.Interaction,
    error: discord.app_commands.AppCommandError,
) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You must be a server administrator to use this command.",
            ephemeral=True,
        )
    else:
        raise ValueError("Command error that wasn't a permission error.")
        # error = error.original


@bot.tree.command(description="Add a user to be tracked")
@app_commands.describe(api_key="API Key used in Wingman")
async def adduser(interaction: discord.Interaction, api_key: str) -> None:
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
    await interaction.response.send_message("Saving API Key.", ephemeral=True)


@bot.tree.command(description="Start tracking bosses")
@app_commands.describe(content_type="The content you want to track")
async def track(
    interaction: discord.Interaction,
    content_type: Literal["fractals", "raids", "raids cm", "strikes", "strikes cm", "golem"],
) -> None:
    user = interaction.user.id
    if user not in workingdata["user"]:
        await interaction.response.send_message(
            "You are not a registered user. Do /adduser",
        )
        return

    workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user][
        "tracked_boss_ids"
    ].union(
        boss_content_lists[content_type],
    )

    await interaction.response.send_message(
        "Added bosses to track list. Next /check will not give PBs to reduce spam.",
        ephemeral=True,
    )
    # Dont spam next time they do /check
    workingdata["user"][user]["lastchecked"] = None
    savedata()


@bot.tree.command(description="Manually check for new PBs")
async def check(interaction: discord.Interaction) -> None:
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
                (
                    "You haven't checked logs yet this patch. "
                    "Not linking PBs to reduce spam. "
                    "Next time /check will link all PB logs"
                ),
                ephemeral=True,
            )
            workingdata["user"][userid]["lastchecked"] = dt.now(UTC)  # Update last checked
            savedata()
            return

        with urllib.request.urlopen(
            f"https://gw2wingman.nevermindcreations.de/api/getPlayerStats?apikey={APIKey}",
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
                        (
                            f"New best DPS log on {bossdump[boss_id]['name']}!\n"
                            f"Spec: {spec}\nDPS: {topstats[boss][spec]['topDPS']}\n"
                            f"Link: https://gw2wingman.nevermindcreations.de/log/{topstats[boss][spec]['link']}"
                        ),
                    )

        # Look for new fastest log
        toptimes = playerstatdump["topBossTimes"][mostrecentpatchid]
        bossescleared = list(set(tracked_boss_ids).intersection(toptimes.keys()))
        for boss in bossescleared:
            # Remove negative from id if present so we can pull boss name from api
            boss_id = boss[1:] if boss.startswith("-") else boss
            logtimestamp = logtimestampfromlink(toptimes[boss]["link"])
            if logtimestamp > workingdata["user"][userid]["lastchecked"]:
                bosstime = dt.fromtimestamp(toptimes[boss]["durationMS"] / 1000.0).strftime(
                    "%M:%S.%f",
                )[:-3]
                responses.append(
                    f"New fastest log on {bossdump[boss_id]['name']}!\nTime: {bosstime}\nLink: https://gw2wingman.nevermindcreations.de/log/{toptimes[boss]['link']}",
                )

        if not responses:
            await interaction.response.send_message("No new PBs")
        else:
            await interaction.response.defer()
            for response in responses:
                await interaction.followup.send(response)

        workingdata["user"][userid]["lastchecked"] = dt.now(UTC)  # Update last checked
        savedata()
    elif workingdata["user"][userid]["apikey"] is None:
        await interaction.response.send_message(
            "Error. You need to add your api key first. Do /adduser",
        )
    else:
        await interaction.response.send_message(
            "Error. You don't have any tracked bosses. Do /track",
        )


@bot.tree.command(description="Add tracking for when game adds new boss")
@app_commands.describe(new_boss_id="New boss id, add both positive and negative if CM")
@commands.is_owner()
async def addnewbossid(
    interaction: discord.Interaction,
    boss_type: Literal["fractals", "raids", "strikes", "golem"],
    new_boss_id: str,
) -> None:
    # Example boss of each type we search to find channels with each type
    bossid = example_boss_ids[boss_type]

    rows = fetch_sql(
        """SELECT DISTINCT id, type, lowman FROM bossserverchannels WHERE boss_id = ?""",
        (bossid,),
    )

    insertsql = """INSERT INTO bossserverchannels VALUES(?,?,?,?)"""
    for channel_id, channel_type, lowman in rows:
        execute_sql(insertsql, (channel_id, new_boss_id, channel_type, lowman))

    logger.info(f"Added new boss id: {new_boss_id} to bosstype: {boss_type!s}")
    await interaction.response.send_message(f"Success! Added boss {len(rows)} times")


@bot.tree.command(description="Remove tracking for when I fuck up")
@app_commands.describe(new_boss_id="New boss id, add both positive and negative if CM")
@commands.is_owner()
async def removenewbossid(
    interaction: discord.Interaction,
    boss_type: Literal["fractals", "raids", "strikes", "golem"],
    new_boss_id: str,
) -> None:
    # Example boss of each type we search to find channels with each type
    bossid = example_boss_ids[boss_type]

    rows = fetch_sql(
        """SELECT DISTINCT id, type, lowman FROM bossserverchannels WHERE boss_id = ?""",
        (bossid,),
    )

    deletesql = (
        "DELETE FROM bossserverchannels WHERE id = ? AND boss_id = ? AND type = ? AND lowman = ?"
    )
    for channel_id, channel_type, lowman in rows:
        execute_sql(deletesql, (channel_id, new_boss_id, channel_type, lowman))

    logger.info(f"Removed boss id: {new_boss_id} to bosstype: {boss_type}")
    await interaction.response.send_message(f"Success! Removed boss {len(rows)} times")


@bot.tree.command(description="What the heck is going on")
@commands.is_owner()
async def debugchannels(interaction: discord.Interaction) -> None:
    rows = fetch_sql("""SELECT DISTINCT id, type FROM bossserverchannels""")
    dpschannelids = [item[0] for item in rows if item[1] == "dps"]
    timechannelids = [item[0] for item in rows if item[1] == "time"]
    supportdpschannelids = [item[0] for item in rows if item[1] == "supportdps"]
    channel_ids = list(set(dpschannelids + timechannelids + supportdpschannelids))

    for channel_id in channel_ids:
        channel = bot.get_channel(channel_id)
        logger.debug(channel_id)
        try:
            logger.debug(channel.guild.unavailable)  # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]
            logger.debug(channel.guild.name)  # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]
            logger.debug(channel.guild.owner.name)  # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]
        except:  # noqa: E722
            logger.exception("Guild info did not work")
            continue
    await interaction.response.send_message("Results sent to log.")


@bot.tree.command(description="Remove channel_id from database")
@commands.is_owner()
async def prune_channel(interaction: discord.Interaction, channel_id: str) -> None:
    logger.info(f"Removing channel: {channel_id}")
    execute_sql("""DELETE FROM bossserverchannels WHERE id = ?""", (channel_id))
    await interaction.response.send_message("Success!")


def construct_bossnamelinks_and_stats(
    boss_id: str,
    patch_id: str,
    playerstatdump: dict,
    leaderboard: Literal["time", "dps", "support"],
    spec: str,
) -> tuple[str, str]:
    bossname = (
        f"{bossidtoname[boss_id[1:]]} CM" if boss_id.startswith("-") else bossidtoname[boss_id]
    )

    if leaderboard == "time":
        link = f"https://gw2wingman.nevermindcreations.de/log/{playerstatdump['topBossTimes'][patch_id][boss_id]['link']}"
        stat = dt.fromtimestamp(
            playerstatdump["topBossTimes"][patch_id][boss_id]["durationMS"] / 1000,
        ).strftime("%M:%S.%f")[:-3]
        return f"[{bossname}]({link})", stat
    if leaderboard == "dps":
        link = f"https://gw2wingman.nevermindcreations.de/log/{playerstatdump['topPerformances'][patch_id][boss_id][spec]['link']}"
        stat = str(playerstatdump["topPerformances"][patch_id][boss_id][spec]["topDPS"])
        return f"[{bossname}]({link})", stat
    if leaderboard == "supportdps":
        link = f"https://gw2wingman.nevermindcreations.de/log/{playerstatdump['topPerformancesSupport'][patch_id][boss_id][spec]['link']}"
        stat = str(playerstatdump["topPerformancesSupport"][patch_id][boss_id][spec]["topDPS"])
        return f"[{bossname}]({link})", stat
    raise ValueError("Unknown Leaderboard Type")


@bot.tree.command(description="Flex on your friends by sharing your best logs.")
@app_commands.describe(
    leaderboard="Which type of leaderboard you would like to show.",
    patch_id=(
        "Optional - Patch ID, by default will show the latest. Patch IDs are generally 'YY-MM'"
    ),
    content=(
        "Optional - The bosses you would like to show organized by content type. "
        "Defaults to all. Includes normal and CMs."
    ),
    spec=(
        "Optional - The specialization you want to show. "
        "Defaults to overall which includes all specs. "
        "Cannot be used with time leaderboard"
    ),
)
async def flex(
    interaction: discord.Interaction,
    leaderboard: Literal["time", "dps", "support"],
    patch_id: str | None = "latest",
    content: Literal["raids", "fractals", "strikes", "all"] | None = "all",
    spec: str | None = "overall",
) -> None:
    await interaction.response.defer(thinking=True)
    # Check for apikey and retrieve data
    userid = interaction.user.id
    rows = fetch_sql(f"""SELECT DISTINCT apikey FROM users WHERE id = '{userid}'""")
    if rows == [] or len(rows) > 1:
        await interaction.followup.send("API-Key Error. Do /adduser with your API-key")
        return
    if spec != "overall" and leaderboard == "time":
        await interaction.followup.send(
            (
                "Error. Currently do not support time leaderboard filtered by specialization. "
                "Try again without specifying the specialization."
            ),
        )
        return
    apikey = rows[0][0]
    logger.debug("Found API key {apikey}")

    with urllib.request.urlopen(
        f"https://gw2wingman.nevermindcreations.de/api/getPlayerStats?apikey={apikey}",
    ) as url:
        playerstatdump = json.load(url)

    # Handle the command arguments
    if patch_id == "latest":
        patch_id = list(playerstatdump["topBossTimes"].keys())[-2]

    bossescompleted = set(playerstatdump["topBossTimes"][patch_id].keys())
    bossestocheck = boss_content_sets[content]  # pyright: ignore[reportArgumentType]

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
    for boss_id in boss_ids:
        if (
            leaderboard == "support"
            and playerstatdump["topPerformancesSupport"][patch_id][boss_id][spec]["topDPS"] == 0
        ):
            continue
        if spec in playerstatdump["topPerformances"][patch_id][boss_id]:
            bossnamelink, stat = construct_bossnamelinks_and_stats(
                boss_id,
                patch_id,  # pyright: ignore[reportArgumentType]
                playerstatdump,
                leaderboard,
                spec,  # pyright: ignore[reportArgumentType]
            )
            bossnamelinks.append(bossnamelink)
            stats.append(stat)

    if leaderboard == "support" and not bossnamelinks:
        await interaction.followup.send("Did not find any support logs for your settings.")
        return

    titletext = {"dps": "DPS", "support": "Support DPS", "time": "Time"}
    bossnamebody, statbody = embed_wrap(bossnamelinks, stats)
    for i, body in enumerate(bossnamebody):
        embed.add_field(name="Boss", value=body, inline=True)
        embed.add_field(
            name=f"{titletext[leaderboard]}",
            value=statbody[i],
            inline=True,
        )
        embed.add_field(name=" ", value=" ")
    await interaction.followup.send(embed=embed)


@bot.tree.command(description="Links the about info")
async def about(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="View github",
        url="https://github.com/SuperClicheUsername/GW2WingmanPBBot",
    )
    await interaction.response.send_message(
        (
            "Discord bot to help track personal bests and patch records from GW2Wingman. "
            "Contact Discord name: supercliche."
        ),
        embed=embed,
    )


@bot.tree.command(
    description=(
        "In the channel where the command is called, "
        "post a message when there is a new patch record"
    ),
)
@app_commands.describe(content_type="The content you want to track")
@app_commands.checks.has_permissions(administrator=True)
# @app_commands.checks.bot_has_permissions(send_message=True, embed_links=True, view_channel=True)
@commands.guild_only()
async def channeltrackboss(
    interaction: discord.Interaction,
    ping_type: Literal["dps", "time", "supportdps"],
    content_type: Literal[
        "fractals",
        "raids",
        "raids cm",
        "strikes",
        "strikes cm",
        "golem",
        "all",
    ],
    only_lowmans: Literal["True", "False"],
) -> None:
    only_lowmans = bool(only_lowmans)  # pyright: ignore[reportAssignmentType]
    if content_type == "golem" and ping_type != "dps":
        await interaction.response.send_message(
            "Only DPS ping type is supported for golems. Try again.",
        )
        return

    await interaction.response.defer(thinking=True)

    sql = """INSERT INTO bossserverchannels VALUES(?,?,?,?)"""
    for boss_id in boss_content_lists[content_type]:
        execute_sql(sql, (interaction.channel_id, boss_id, ping_type, only_lowmans))

    await interaction.followup.send(
        (
            "Added bosses to track list. "
            "Will post in this channel when the next patch record is posted"
        ),
    )
    return


@bot.tree.command(
    description="Untrack bosses from automatic ping list when a new patch record is added",
)
@app_commands.describe(content_type="The content you want to track")
@app_commands.checks.has_permissions(administrator=True)
@commands.guild_only()
async def channeluntrackboss(
    interaction: discord.Interaction,
    ping_type: Literal["dps", "time", "supportdps"],
    content_type: Literal[
        "fractals",
        "raids",
        "raids cm",
        "strikes",
        "strikes cm",
        "golem",
        "all",
    ],
    only_lowmans: Literal["true", "false"],
) -> None:
    await interaction.response.defer(thinking=True)

    sql = """DELETE FROM bossserverchannels WHERE id=? AND boss_id=? AND type=? AND lowman=?"""
    for boss_id in boss_content_lists[content_type]:
        execute_sql(sql, (interaction.channel_id, boss_id, ping_type, only_lowmans))

    await interaction.followup.send("Removed bosses from track list.")


@bot.event
async def pingreportedlog(content: dict) -> None:
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
        bot.loop.create_task(channel.send(embed=log))  # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]
    except Exception:
        logger.exception("Reported log could not be pinged")
    logger.debug(f"Log reported {loglink}, reason: {reasontext}")


@bot.event
async def internalmessage(content: dict) -> None:
    # Echos any message sent to the /internalmessage/ endpoint to the internal botspam channel
    await bot.wait_until_ready()
    message = content["message"]
    internalmessagechannel = 1208602365972717628

    channel = bot.get_channel(internalmessagechannel)
    try:
        bot.loop.create_task(channel.send(content=message))  # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]
    except Exception:
        logger.exception("Internal message could not be sent")

    logger.debug(f"Internal message {message}")


def determine_era(content: dict, patchidlist: list) -> str | None:
    if content["eraID"] == "all":
        return "All Time"
    if content["eraID"] not in patchidlist:
        importlib.reload(startupvars)
        return "Current Patch"
    if content["eraID"] == patchidlist[0]:
        return "Current Patch"
    logger.debug("Record for old patch, ignoring")
    return None


def construct_embed(
    title: str,
    url: str,
    groups: str,
    iconurl: str,
    fields: list[tuple[str, str, bool]],
) -> discord.Embed:
    log = discord.Embed(title=title, url=url)
    if groups:
        log.add_field(name="Group", value=groups, inline=False)
    log.set_thumbnail(url=iconurl)
    for name, value, inline in fields:
        log.add_field(name=name, value=value, inline=inline)
    return log


def get_icon_url(content: dict, groups: str, bossid: str, bossdump: dict) -> str:
    # Get the default boss icon
    if bossid.startswith("-"):
        bossid = bossid[1:]
    iconurl = f"https://gw2wingman.nevermindcreations.de{bossdump[bossid]['icon']}"

    # If in a group and group has icon use that instead
    if groups:
        groupicon = urlquote(content["groupIcons"][0], safe=":/")
        if groupicon != "https://gw2wingman.nevermindcreations.de/static/groupIcons/defGroup.png":
            iconurl = groupicon

    return iconurl


@bot.event
async def patchtimerecord(content: dict) -> None:
    await bot.wait_until_ready()
    bossid: str = content["bossID"]
    islowman = False
    if "isLowman" in content:
        islowman = bool(content["isLowman"])
        prev_player_count: int = content["previousPlayerAmount"]

    if islowman:
        rows = fetch_sql(
            "SELECT DISTINCT id FROM bossserverchannels WHERE boss_id=? AND type=? AND lowman=true",
            (bossid, "time"),
        )
    else:
        rows = fetch_sql(
            (
                "SELECT DISTINCT id FROM bossserverchannels WHERE boss_id=? "
                "AND type=? AND lowman=false"
            ),
            (bossid, "time"),
        )

    if "isDebug" in content:
        rows = [(1070109613355192370,)]
        logger.debug("Debug post")
        logger.debug(content)

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
        "%M:%S.%f",
    )[:-3]
    loglink = content["link"]

    iconurl = get_icon_url(content, groups, bossid, bossdump)
    emoji_list = [str(get(bot.emojis, name=spec)) for spec in content["players_professions"]]
    playerscontent = "\n".join(
        f"{m} {n}/{o}" for m, n, o in zip(emoji_list, players, accts, strict=False)
    )

    fields = [
        ("Time", time, True),
        ("Previous Time", prevtime, True),
        ("Era", era, True),
        ("Players", playerscontent, False),
    ]
    title = f"New fastest log on {bossname}"
    if islowman:
        fields = [
            ("Time", time, True),
            ("Previous Time", prevtime, True),
            ("Previous Player Count", prev_player_count, True),  # pyright: ignore[reportPossiblyUnboundVariable]
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


async def send_log(
    channel: discord.abc.GuildChannel | discord.Thread | discord.abc.PrivateChannel,
    log: discord.Embed,
) -> None:
    """Handle sending a message and logs any errors."""
    try:
        await channel.send(embed=log)  # pyright: ignore[reportAttributeAccessIssue]
    except Exception:
        logger.exception(f"Failed to write to channel {channel.id}")


def send_records(rows: list[tuple[int]], log: discord.Embed) -> None:
    for row in rows:
        channel = bot.get_channel(row[0])
        if channel is None:
            continue
        bot.loop.create_task(send_log(channel, log))


@bot.event
async def patchdpsrecord(
    content: dict,
    leaderboardtype: Literal["dps", "supportdps"] = "dps",
) -> None:
    await bot.wait_until_ready()
    bossid: str = content["bossID"]
    rows = fetch_sql(
        "SELECT DISTINCT id FROM bossserverchannels WHERE boss_id=? AND type=?",
        (bossid, leaderboardtype),
    )

    # Dont keep going if no channel wants the ping
    if not rows:
        logger.debug("Nobody wanted this ping")
        return

    if "isDebug" in content:
        rows = [(1070109613355192370,)]
        logger.debug("Debug post")
        logger.debug(content)

    bossname = bossname_from_id(content, bossid)
    era = determine_era(content, patchidlist)
    if era is None:
        return

    charname = content["character"]
    profession = content["profession"]
    dps: int = content["dps"]
    dpsdiff = dps - content["previousDps"]
    dpsstring = f"{dps!s} (+{dpsdiff})"
    acctname = content["account"]

    if acctname == "Conjured Sword" or profession is None:
        logger.debug("Skipping ping for Conjured Sword/Unknown profession")
        return

    groups = ", ".join(content["group"])
    loglink = content["link"]
    titletext = {"dps": "DPS", "supportdps": "Support DPS"}
    iconurl = get_icon_url(content, groups, bossid, bossdump)

    emoji = get(bot.emojis, name=profession)
    playercontent = f"{emoji!s} {charname}/{acctname}"

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


def bossname_from_id(content: dict, bossid: str) -> str:
    #  Negative boss IDs are CMs
    if bossid.startswith("-"):
        # Check for legendary key first because not all bosses will have it
        if "isLegendaryCM" in content:
            if content["isLegendaryCM"]:
                return content["bossName"] + " LCM"
        else:
            return content["bossName"] + " CM"
    else:
        return content["bossName"]
    raise ValueError


with open("data/discord_token.txt") as f:
    token = f.readline()


def run_discord_bot() -> None:
    bot.run(token)
