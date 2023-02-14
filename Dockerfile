# Remove old container
# docker stop wingmanbot
# docker rm -f wingmanbot
# docker image rm -f wingmanbot

# Build new container
# docker build -t wingmanbot -f Dockerfile . 

# volume must contain bot token and workingdata.pkl (only has to be done for first setup)
# docker run -p 5005:5005 --network="host" -v /srv/wingmanbotdata:/app/data --name wingmanbot wingmanbot
FROM python:3.10-slim

EXPOSE 5005

WORKDIR /app

COPY . .

RUN pip3 install -r requirements.txt

CMD ["hypercorn", "app:app", "-b", "0.0.0.0:5005"]