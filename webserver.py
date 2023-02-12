from flask import Flask, request
import json
from bot import personaldps

app = Flask(__name__)


def run_webserver():
    app.run(host="0.0.0.0", port=5005, debug=True)


@app.route("/")
def hello(): return "Hello World"


@app.route('/patchrecord/', methods=['POST'])
def patchrecord():
    content_type = request.headers.get('Content-Type')
    if (content_type == 'application/json'):
        data = request.get_json()
        with open('data.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        return "Success"
    else:
        return "Content-Type not supported!"


@app.route('/personalbest/', methods=['POST'])
def personalbest():
    content_type = request.headers.get('Content-Type')
    if (content_type == 'application/json'):
        data = request.get_json()

        if data["type"] == "time":
            # personaltime(data)
            pass
        elif data["type"] == "dps":
            personaldps(data)

        return "Success"
    else:
        return "Content-Type not supported!"
