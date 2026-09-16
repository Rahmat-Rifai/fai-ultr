# Discord Bot ERPG Automation

Aumatic Script That Can handle task Using
REST API.
a
## feature

-   Auto RPG cycle loop
-   NeonUtil Dungeon 
-   Detection HTTP captcha
-   Detection EPIC RPG in-game captcha
-   Detection Lucy CAPTCHA / anti-bot challenge (risk scoring + automatic stop)
-   Auto handle rate limit (429)
-   Logging ke file

## Requirements

Python 3.9+

Install dependency: requirements.txt

## config

change example to .env

TOKEN=your_discord_token
CHANNEL_ID=your_channel_id
NEONUTIL_TARGET_ID=target_bot_id
LUCY_BOT_ID=lucy_bot_user_id

Optional CAPTCHA detection settings:

CAPTCHA_DETECTION_ENABLED=true
CAPTCHA_STOP_THRESHOLD=5
CAPTCHA_MONITOR_MODE=true
CAPTCHA_LOG_ENABLED=true

-   `LUCY_BOT_ID`: primary identification of Lucy (bot user ID). If empty,
    falls back to bot flag + display name "Lucy".
-   `CAPTCHA_STOP_THRESHOLD`: risk score that triggers a stop (default 5).
-   `CAPTCHA_MONITOR_MODE=true`: suspicious messages are only logged
    (FLAGGED ONLY); high-confidence CAPTCHAs still stop the bot. Set to
    `false` for strict mode (score >= threshold stops immediately).
-   `CAPTCHA_LOG_ENABLED`: write trigger details to lucy_captcha_log.txt.

## Run

python main.py

## Reset after CAPTCHA stop

When Lucy sends a high-confidence CAPTCHA, all automation is stopped
(idempotent) and no new commands are sent. Reset is manual only:

```python
from automation_state import reset_automation
reset_automation()
```

## Tests

pytest

Unit tests cover the Lucy CAPTCHA detector (normal messages stay normal,
CAPTCHA messages stop the bot, stop is idempotent).

