# GW2WingmanPBBot

A discord bot with features from [Gw2 Wingman](https://gw2wingman.nevermindcreations.de/)

[Invite the bot to your Discord Server!](https://discord.com/api/oauth2/authorize?client_id=1070108638116597790&permissions=2147633152&scope=bot)

Join the Wingman [Discord Server!](https://discord.gg/zPGwZYUnPH)

## Contact:
* Discord: Yukino Y#0865
* Ingame: dude.3905

## Features:
* Check for new PB DPS logs
* Check for new PB time logs
## Future features(soonTM):
* Compare DPS PB log to patch record log
* Compare time PB log to patch record log
* Automatic ping when new PB logs are detected
* Receive a ping when your wingman leaderboard position changes
* Role-based pings for new top DPS log
* Receive a ping for new patch record log

# Running PBBot

### Discord
Setup instructions modified from [Toothy](https://github.com/Maselkov/Toothy) (Thanks!)

1. Login to [Discord Developer Portal](https://discord.com/developers/applications) and click "New Application".

2. After creating a new application, go to the Bot tab and click the *Add Bot* button.  
    * Save the ***Bot Token*** 
    * Save the ***Application ID***
    
3. Scroll down to the *Privileged Gateway Intents* section and enable all privileged intents, then save changes.

4. Invite your newly created bot to your Discord server by copying the following URL into a browser:  
  (Replace `YOUR_BOT_APPLICATION_ID` with the ***Application ID*** from Step 2)  
  ```
  https://discord.com/api/oauth2/authorize?client_id=YOUR_BOT_APPLICATION_ID&permissions=2147633152&scope=bot
  ```
  
### Deploy
1. Clone the github repository

2. Create another folder for the bot data

3. In that newly created folder create a discord_token.txt file with the ***Bot Token*** inside

4. Also in that newly created folder run the following python commands
```
import pickle
workingdata = {"user":{}}
with open('workingdata.pkl', 'wb') as f:
        pickle.dump(workingdata, f)
```

5. Inside the cloned repository run the following Docker commands
```
docker build -t wingmanbot -f Dockerfile . 
docker run -v <YOUR DATA FOLDER PATH>:/app/data --name wingmanbot wingmanbot
```

## Licensed Works Used

[Toothy](https://github.com/Maselkov/Toothy) by [Maselkov](https://github.com/Maselkov) under [MIT License](https://spdx.org/licenses/MIT.html)
