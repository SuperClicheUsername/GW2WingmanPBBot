import asyncio
import json

# from bot import personaldps, personaltime
from threading import Thread

from quart import Quart, request

from bot import (
    internalmessage,
    patchdpsrecord,
    patchtimerecord,
    pingreportedlog,
    run_discord_bot,
)

app = Quart(__name__)

t = Thread(target=run_discord_bot)
t.daemon = True
t.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=True)


@app.route("/")
async def hello():
    return "Hello World"


@app.route("/patchrecord/", methods=["POST"])
async def patchrecord():
    content_type = request.headers.get("Content-Type")
    if content_type != "application/json":
        return "Content-Type not supported!"
    data = await request.get_json()

    print(data)

    if data["type"] == "time":
        await patchtimerecord(data)
    elif data["type"] == "dps":
        await patchdpsrecord(data, leaderboardtype="dps")
    elif data["type"] == "supportdps":
        await patchdpsrecord(data, leaderboardtype="supportdps")

    return "Success"


@app.route("/reportlog/", methods=["POST"])
async def reportlog():
    content_type = request.headers.get("Content-Type")
    if content_type != "application/json":
        return "Content-Type not supported!"
    data = await request.get_json()
    await pingreportedlog(data)

    return "Success"


@app.route("/internalmessage/", methods=["POST"])
async def internalmessaging():
    content_type = request.headers.get("Content-Type")
    if content_type != "application/json":
        return "Content-Type not supported!"

    data = await request.get_json()
    await internalmessage(data)
    return "Success"
