# Discord Bot ERPG Automation

Automates Discord RPG commands via the Discord REST API and stops on CAPTCHA challenges.

## Features

- Automatic RPG cycle loops
- NeonUtil dungeon solver
- Detection for HTTP captchas and EPIC RPG in-game captchas
- Lucy CAPTCHA detection with risk scoring and auto-stop
- Rate limit backoff (HTTP 429)
- Incident and cycle logging to file

## Requirements

- Python 3.9+
- Discord user token

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Create a `.env` file from the variables below:
   ```env
   TOKEN=your_discord_token
   CHANNEL_ID=your_channel_id
   NEONUTIL_TARGET_ID=target_bot_id
   LUCY_BOT_ID=lucy_bot_user_id

   # Optional CAPTCHA detection settings
   CAPTCHA_DETECTION_ENABLED=true
   CAPTCHA_STOP_THRESHOLD=5
   CAPTCHA_MONITOR_MODE=true
   CAPTCHA_LOG_ENABLED=true
   ```

   - `LUCY_BOT_ID`: Lucy bot user ID. If empty, falls back to bot flag and display name.
   - `CAPTCHA_STOP_THRESHOLD`: Risk score threshold to stop the bot (default: 5).
   - `CAPTCHA_MONITOR_MODE`: If `true`, suspicious messages are only logged without halting. If `false`, a score >= threshold stops immediately.
   - `CAPTCHA_LOG_ENABLED`: Writes trigger details to `lucy_captcha_log.txt`.

## Run

```bash
python main.py
```

## Reset After CAPTCHA Stop

When a high-confidence CAPTCHA triggers a stop, automation halts immediately. To reset:

```python
from automation_state import reset_automation
reset_automation()
```

## Tests

Run the test suite with pytest:

```bash
pytest
```
