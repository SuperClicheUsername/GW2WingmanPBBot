import json
import pickle
import ssl
import urllib.request
from datetime import datetime as dt
from datetime import timezone
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands, tasks

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

# Grab class specs
with urllib.request.urlopen("https://gw2wingman.nevermindcreations.de/api/classes") as url:
    classdump = json.load(url)
professions = list(classdump.keys())


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
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')
    # my_task.start()

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
    workingdata["user"][interaction.user.id] = {
        "apikey": None,
        "tracked_boss_ids": set(),
        "lastchecked": None
    }

    if isapikeyvalid(apikey):
        workingdata["user"][interaction.user.id]["apikey"] = apikey
        await interaction.response.send_message("Valid API key. Saving. Do /track next")
        savedata()
    else:
        await interaction.response.send_message("Invalid API key try again.")


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
    await interaction.response.send_message("Added bosses to track list")
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

        if workingdata["user"][userid]["lastchecked"] is None or workingdata["user"][userid]["lastchecked"] < mostrecentpatchstart:
            interaction.response.send_message(
                "You haven't checked logs yet this patch. Not linking PBs to reduce spam. Next time /check will link all PB logs")
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
        await interaction.response.send_message("You are not a registered user. Do /adduser")
        return

    workingdata["user"][userid]["lastchecked"] = dt.strptime(
        mostrecentpatchstart + " 12:30 -0000", "%Y-%m-%d %H:%M %z")
    await interaction.response.send_message("Last checked reset to most recent patch day")


@bot.tree.command(description="Responds with the last time PBs were checked")
# @app_commands.describe()
async def lastchecked(interaction: discord.Interaction):
    userid = interaction.user.id
    if userid not in workingdata["user"].keys():
        await interaction.response.send_message("You are not a registered user. Do /adduser")
        return
    if workingdata["user"][userid]["lastchecked"] is None:
        await interaction.response.send_message("You have never checked logs before.")
        return

    lastchecked = workingdata["user"][userid]["lastchecked"]
    delta = dt.now(timezone.utc) - lastchecked
    days, remainder = divmod(delta.total_seconds(), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    await interaction.response.send_message("Last checked " + f"{int(days)} days, {int(hours)} hours, {int(minutes)} minutes" + " ago")

# @tasks.loop(seconds=10)  # task runs every 10 seconds
# async def my_task():
#     # Make sure the list of users isnt empty
#     if hasattr(workingdata["user"], '__iter__'):
#         for userid in workingdata["user"]:
#             user = await bot.fetch_user(userid)
#             if workingdata["user"]["apikey"] is not None and "tracked_boss_ids" != []:
#                 await user.send("This should ping every 10 seconds. This is where we check for new logs")

with open('data/discord_token.txt') as f:
    token = f.readline()

bot.run(token)
