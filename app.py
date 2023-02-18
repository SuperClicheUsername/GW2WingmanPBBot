from quart import Quart, request
import json
import asyncio
from bot import run_discord_bot, personaldps, bot, patchdpsrecord, patchtimerecord
from threading import Thread

app = Quart(__name__)

t = Thread(target=run_discord_bot)
t.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=True)


@app.route('/')
async def hello():
    return 'Hello World'


@app.route('/patchrecord/', methods=['POST'])
async def patchrecord():
    content_type = request.headers.get('Content-Type')
    if (content_type == 'application/json'):
        data = await request.get_json()
        # Some debug crap
        print(data)
        with open('data/data.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        if data["type"] == "time":
            await patchtimerecord(data)
        elif data["type"] == "DPS":
            await patchdpsrecord(data)

        return "Success"
    else:
        return "Content-Type not supported!"


@app.route('/personalbest/', methods=['POST'])
async def personalbest():
    content_type = request.headers.get('Content-Type')
    if (content_type == 'application/json'):
        data = await request.get_json()

        if data["type"] == "time":
            # await personaltime(data)
            pass
        elif data["type"] == "DPS":
            await personaldps(data)

        return "Success"
    else:
        return "Content-Type not supported!"
