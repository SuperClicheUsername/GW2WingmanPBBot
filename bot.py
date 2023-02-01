import json
import pickle
import ssl
import urllib.request
from datetime import datetime as dt
from datetime import timezone

import discord
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


description = '''An example bot to showcase the discord.ext.commands extension
module.
There are a number of utility commands being showcased here.'''

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix='?',
                   description=description, intents=intents)
#workingdata = {"user":{}}


def savedata():
    with open('workingdata.pkl', 'wb') as f:
        pickle.dump(workingdata, f)
    return None


def isapikeyvalid(key):
    with urllib.request.urlopen("https://gw2wingman.nevermindcreations.de/api/getPlayerStats?apikey={}".format(key)) as url:
        playerstatdump = json.load(url)
    if "error" in playerstatdump.keys():
        return False
    else:
        return True


@bot.event
async def on_ready():
    global workingdata
    with open('workingdata.pkl', 'rb') as f:
        workingdata = pickle.load(f)
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


@bot.command(description="Add a user to be tracked")
async def adduser(ctx):
    workingdata["user"][ctx.author.id] = {
        "apikey": None,
        "tracked_boss_ids": set(),
        "lastchecked": dt.strptime(mostrecentpatchstart + " 12:30 -0500", "%Y-%m-%d %H:%M %z")
    }
    await ctx.send("Send me your API Key used in Wingman. Reply with your api key")

    def check(msg):
        return msg.author == ctx.author and msg.guild is None

    response = await bot.wait_for("message", check=check)
    apikey = response.content.strip()

    if isapikeyvalid(apikey):
        workingdata["user"][ctx.author.id]["apikey"] = apikey
        await ctx.send("Valid API key. Saving. Do ?track [fractals,raids,strikes] next")
        savedata()
    else:
        await ctx.send("Invalid API key try again.")


@bot.command(description="Start tracking bosses")
async def track(ctx):
    content = ctx.message.content
    user = ctx.message.author.id
    content = content[7:]  # Remove command phrase
    if content == "fractals":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user]["tracked_boss_ids"].union(
            fractal_cm_boss_ids)
        savedata()
        await ctx.send("Added bosses to track list")
    elif content == "raids":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user]["tracked_boss_ids"].union(
            raid_boss_ids)
        savedata()
        await ctx.send("Added bosses to track list")
    elif content == "raids cm":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user]["tracked_boss_ids"].union(
            raid_cm_boss_ids)
        savedata()
        await ctx.send("Added bosses to track list")
    elif content == "strikes":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user]["tracked_boss_ids"].union(
            strike_boss_ids)
        savedata()
        await ctx.send("Added bosses to track list")
    elif content == "strikes cm":
        workingdata["user"][user]["tracked_boss_ids"] = workingdata["user"][user]["tracked_boss_ids"].union(
            strike_cm_boss_ids)
        savedata()
        await ctx.send("Added bosses to track list")
    else:
        await ctx.send("Invalid response please try again with [fractals, raids, raids cm, strikes, strikes cm]")


@bot.command(description="Check for new PBs")
async def check(ctx):
    userid = ctx.message.author.id
    sentlog = False
    if workingdata["user"][userid]["apikey"] is not None and workingdata["user"][userid]["tracked_boss_ids"] != set():
        APIKey = workingdata["user"][userid]["apikey"]
        tracked_boss_ids = workingdata["user"][userid]["tracked_boss_ids"]

        with urllib.request.urlopen("https://gw2wingman.nevermindcreations.de/api/getPlayerStats?apikey={}".format(APIKey)) as url:
            playerstatdump = json.load(url)
        format_data = "%Y%m%d-%H%M%S %z"

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
                logtimestamp = topstats[boss][spec]["link"][:15] + " -0500"
                logtimestamp = dt.strptime(logtimestamp, format_data)
                # Check if log timestamps are from after last check
                if logtimestamp > workingdata["user"][userid]["lastchecked"]:
                    sentlog = True
                    await ctx.send("New best DPS log on {}!\nSpec: {}\nDPS: {}\nLink: https://gw2wingman.nevermindcreations.de/log/{}".format(bossdump[boss_id]["name"], spec, topstats[boss][spec]["topDPS"], topstats[boss][spec]["link"]))

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
            logtimestamp = toptimes[boss]["link"][:15] + " -0500"
            logtimestamp = dt.strptime(logtimestamp, format_data)
            # Check if log timestamps are from after last check
            if logtimestamp > workingdata["user"][userid]["lastchecked"]:
                bosstime = dt.fromtimestamp(
                    toptimes[boss]["durationMS"]/1000.0).strftime('%M:%S.%f')[:-3]
                sentlog = True
                await ctx.send("New fastest log on {}!\nTime: {}\nLink: https://gw2wingman.nevermindcreations.de/log/{}".format(bossdump[boss_id]["name"], bosstime, toptimes[boss]["link"]))

        if not sentlog:
            await ctx.send("No new PBs")

        workingdata["user"][userid]["lastchecked"] = dt.now(
            timezone.utc)  # Update last checked
        savedata()


@bot.command(description="Debug command to reset last checked")
async def resetlastchecked(ctx):
    userid = ctx.message.author.id
    workingdata["user"][userid]["lastchecked"] = dt.strptime(
        mostrecentpatchstart + " 12:30 -0500", "%Y-%m-%d %H:%M %z")
    await ctx.send("Last checked reset")

# @tasks.loop(seconds=10)  # task runs every 10 seconds
# async def my_task():
#     # Make sure the list of users isnt empty
#     if hasattr(workingdata["user"], '__iter__'):
#         for userid in workingdata["user"]:
#             user = await bot.fetch_user(userid)
#             if workingdata["user"]["apikey"] is not None and "tracked_boss_ids" != []:
#                 await user.send("This should ping every 10 seconds. This is where we check for new logs")

with open('discord_token.txt') as f:
    token = f.readline()

bot.run(token)
