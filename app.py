# from bot import personaldps, personaltime
from threading import Thread

from quart import Quart, request

from bot import (
    internalmessage,
    logger,
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
async def hello() -> str:
    return "Hello World"


@app.route("/patchrecord/", methods=["POST"])
async def patchrecord() -> str:
    content_type = request.headers.get("Content-Type")
    if content_type != "application/json":
        return "Content-Type not supported!"
    data: dict[str, str | int | bool | list[str]] = await request.get_json()

    logger.debug(data)

    if data["type"] == "time":
        try:
            await patchtimerecord(data)
        except Exception:
            logger.error(data)
            logger.exception("Patch time record did not ping")
            return "Fail"

    elif data["type"] == "dps":
        try:
            await patchdpsrecord(data, leaderboardtype="dps")
        except Exception:
            logger.error(data)
            logger.exception("Patch DPS record did not ping")
            return "Fail"

    elif data["type"] == "supportdps":
        try:
            await patchdpsrecord(data, leaderboardtype="supportdps")
        except Exception:
            logger.error(data)
            logger.exception("Patch Support DPS record did not ping")
            return "Fail"

    return "Success"


@app.route("/reportlog/", methods=["POST"])
async def reportlog() -> str:
    content_type = request.headers.get("Content-Type")
    if content_type != "application/json":
        return "Content-Type not supported!"
    data: dict[str, str] = await request.get_json()
    await pingreportedlog(data)

    return "Success"


@app.route("/internalmessage/", methods=["POST"])
async def internalmessaging() -> str:
    content_type = request.headers.get("Content-Type")
    if content_type != "application/json":
        return "Content-Type not supported!"

    data: dict[str, str] = await request.get_json()
    await internalmessage(data)
    return "Success"
