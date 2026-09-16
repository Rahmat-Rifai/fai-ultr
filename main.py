import os
import time
import warnings
from datetime import datetime

import requests
import urllib3
import urllib3.util.ssl_
from dotenv import load_dotenv

import automation_state
import lucy_captcha_detector
from captcha_handler import CaptchaHandler
from rpg import execute_rpg_cycle

warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore")

# Relax the OpenSSL security level for every TLS context urllib3 builds.
# The old one-liner (`urllib3.util.ssl_.DEFAULT_CIPHERS = ...`) only worked on
# urllib3 1.x; on urllib3 2.x that module attribute no longer exists, so the
# assignment was silently dead. Patching create_urllib3_context keeps the
# intended behaviour across both versions and applies to every request in the
# program (main.py and lucy_captcha_detector.py alike).
_RELAXED_CIPHERS = "ALL:@SECLEVEL=1"
_orig_create_urllib3_context = urllib3.util.ssl_.create_urllib3_context


def _create_urllib3_context_relaxed(*args, **kwargs):
    if kwargs.get("ciphers") is None:
        kwargs["ciphers"] = _RELAXED_CIPHERS
    return _orig_create_urllib3_context(*args, **kwargs)


urllib3.util.ssl_.create_urllib3_context = _create_urllib3_context_relaxed

load_dotenv()

TOKEN = os.getenv("TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
EPIC_RPG_BOT_ID = "555955826880413696"

headers = {"Authorization": TOKEN, "Content-Type": "application/json"}

captcha_handler = CaptchaHandler(TOKEN, max_captcha_attempts=1)


def send_message(content, delay_after=0):
    # Refuse to send any new command once the automation has been stopped.
    if not automation_state.bot_running:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] AUTOMATION STOPPED — refusing to send: {content}"
        )
        return False

    url = f"https://discord.com/api/v9/channels/{CHANNEL_ID}/messages"
    payload = {"content": content, "tts": False}

    try:
        response = requests.post(
            url, headers=headers, json=payload, verify=False, timeout=30
        )  # noqa: S501

        if captcha_handler.handle_captcha_response(response):
            pass

        if response.status_code == 200:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] SENT: {content}")

            # Lucy CAPTCHA detection: check Lucy's latest replies right after
            # our command so automation stops before anything else is sent.
            if lucy_captcha_detector.check_lucy_captcha(headers, CHANNEL_ID):
                return False

            if delay_after > 0:
                time.sleep(delay_after)
            return True
        elif response.status_code == 401:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: Token invalid")
            return False
        elif response.status_code == 429:
            retry_after = response.json().get("retry_after", 2)
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] RATE LIMITED: Waiting {retry_after}s"
            )
            time.sleep(retry_after)
            if not automation_state.bot_running:
                return False
            return send_message(content, delay_after)
        else:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: HTTP {response.status_code}"
            )
            if captcha_handler.detect_captcha(response):
                captcha_handler.handle_captcha_response(response)
            return False
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: {e}")
        return False


def main():

    print()

    input("Press ENTER to start (Ctrl+C to stop)...\n")

    cycle_count = 1

    # Handler placeholder for the optional NEONUTIL monitor sequence inside an
    # RPG cycle. RPG_TASKS does not currently emit that command, so the handler
    # is a safe no-op, but execute_rpg_cycle requires a callable at this slot.
    def neonutil_handler():
        pass

    try:
        while True:
            if not automation_state.bot_running:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] AUTOMATION STOPPED — exiting main loop"
                )
                break

            # Monitor Lucy for CAPTCHA before starting each cycle.
            if lucy_captcha_detector.check_lucy_captcha(headers, CHANNEL_ID):
                break

            success = execute_rpg_cycle(cycle_count, send_message, neonutil_handler)
            if not success:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: Cycle failed")
                time.sleep(30)

            cycle_count += 1

            if not automation_state.bot_running:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] AUTOMATION STOPPED — exiting main loop"
                )
                break

            print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting 2 seconds")
            time.sleep(2)

    except KeyboardInterrupt:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Script stopped manually")
        print(f"Total cycles: {cycle_count - 1}")

        with open("rpg_cycles.log", "a") as f:
            f.write(
                f"\nScript stopped manually after {cycle_count - 1} cycles at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            )

    except SystemExit:
        print(
            f"\n[{datetime.now().strftime('%H:%M:%S')}] Script terminated due to captcha"
        )
        print(f"Total cycles completed: {cycle_count - 1}")

    except Exception as e:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ERROR: {e}")
        time.sleep(60)


if __name__ == "__main__":
    main()
