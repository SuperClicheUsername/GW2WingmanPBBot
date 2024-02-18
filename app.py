import asyncio
import json

# from bot import personaldps, personaltime
from threading import Thread

from quart import Quart, request

from bot import cur, patchdpsrecord, patchtimerecord, pingreportedlog, run_discord_bot, internalmessage

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
    if content_type == "application/json":
        data = await request.get_json()

        print(data)

        if data["type"] == "time":
            await patchtimerecord(data, cur)
        elif data["type"] == "dps":
            await patchdpsrecord(data, cur)

        return "Success"
    else:
        return "Content-Type not supported!"


@app.route("/personalbest/", methods=["POST"])
async def personalbest():
    content_type = request.headers.get("Content-Type")
    if content_type == "application/json":
        data = await request.get_json()

        if data["type"] == "time":
            # await personaltime(data, cur)
            pass
        elif data["type"] == "dps":
            # await personaldps(data, cur)
            pass

        return "Success"
    else:
        return "Content-Type not supported!"


@app.route("/reportlog/", methods=["POST"])
async def reportlog():
    content_type = request.headers.get("Content-Type")
    if content_type == "application/json":
        data = await request.get_json()
        await pingreportedlog(data, cur)

        return "Success"
    else:
        return "Content-Type not supported!"

@app.route("/internalmessage/", methods=["POST"])
async def patchrecord():
    content_type = request.headers.get("Content-Type")
    if content_type == "application/json":
        data = await request.get_json()
        await internalmessage(data, cur)
    else:
        return "Content-Type not supported!"