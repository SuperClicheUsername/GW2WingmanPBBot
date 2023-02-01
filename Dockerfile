# docker stop wingmanbot
# docker rm -f wingmanbot
# docker build -t wingmanbot -f Dockerfile . 
# docker run -v botdata:/app/data --name wingmanbot
FROM python:3.10-slim

WORKDIR /app

COPY . .

RUN pip3 install -r requirements.txt

CMD ["python bot.py"]