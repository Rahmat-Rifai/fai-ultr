"""Live test: send lh/lb/lucy, fetch Lucy's replies, run the CAPTCHA detector.

Reads TOKEN/CHANNEL_ID from .env. Prints each Lucy message with its
content/embeds/components/attachments and the detector's decision.
Does NOT stop automation and does NOT log incidents — analysis only.
"""

import os
import time
from datetime import datetime

import httpx


def load_env(path=".env"):
    """Minimal .env parser (python-dotenv not installed in this env)."""
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


_env = load_env()

TOKEN = _env.get("TOKEN")
CHANNEL_ID = _env.get("CHANNEL_ID")

HEADERS = {"Authorization": TOKEN, "Content-Type": "application/json"}

API = "https://discord.com/api/v9"


def send_message(content):
    url = f"{API}/channels/{CHANNEL_ID}/messages"
    for attempt in range(3):
        resp = httpx.post(url, headers=HEADERS, json={"content": content, "tts": False}, verify=False, timeout=30)
        if resp.status_code == 429:
            retry = resp.json().get("retry_after", 2)
            print(f"  RATE LIMITED, waiting {retry}s")
            time.sleep(retry + 0.5)
            continue
        print(f"[{datetime.now().strftime('%H:%M:%S')}] SENT: {content} -> HTTP {resp.status_code}")
        return resp.status_code == 200
    return False


def fetch_messages(limit=25):
    url = f"{API}/channels/{CHANNEL_ID}/messages?limit={limit}"
    resp = httpx.get(url, headers=HEADERS, verify=False, timeout=30)
    if resp.status_code == 200:
        return resp.json()
    print(f"FETCH ERROR: HTTP {resp.status_code} {resp.text[:200]}")
    return []


def describe_message(msg):
    author = msg.get("author") or {}
    lines = []
    lines.append(f"  id={msg.get('id')} author={author.get('username')!r} (id={author.get('id')})")
    content = msg.get("content") or ""
    if content:
        lines.append(f"  content: {content[:300]!r}")
    for i, embed in enumerate(msg.get("embeds") or []):
        lines.append(f"  embed[{i}]: title={embed.get('title')!r} desc={str(embed.get('description'))[:200]!r}")
        for f in (embed.get("fields") or [])[:5]:
            lines.append(f"    field: {f.get('name')!r} = {str(f.get('value'))[:150]!r}")
        if embed.get("footer"):
            lines.append(f"    footer: {embed['footer'].get('text')!r}")
        if embed.get("author"):
            lines.append(f"    author: {embed['author'].get('name')!r}")
        if embed.get("url"):
            lines.append(f"    url: {embed.get('url')!r}")
    for i, comp in enumerate(msg.get("components") or []):
        for c in (comp.get("components") or []):
            label = c.get("label") or c.get("placeholder") or ""
            lines.append(f"  component[{i}]: type={c.get('type')} label={label!r} url={c.get('url')!r}")
    for a in msg.get("attachments") or []:
        lines.append(f"  attachment: {a.get('filename')!r} type={a.get('content_type')!r} size={a.get('size')}")
    return "\n".join(lines)


def main():
    import sys
    import lucy_captcha_detector as lcd

    cycles = 1
    if len(sys.argv) > 1:
        cycles = int(sys.argv[1])
    cooldown = 15

    detector = lcd.CaptchaDetector()

    print(f"Channel: {CHANNEL_ID}")
    print(f"Sending lh, lb, lucy x{cycles} with {cooldown}s cooldown per command ...")
    for cycle in range(1, cycles + 1):
        print(f"--- Cycle {cycle}/{cycles} ---")
        for cmd in ("lh", "lb", "lucy"):
            send_message(cmd)
            time.sleep(cooldown)

    print("Waiting for Lucy's replies ...")
    time.sleep(12)

    messages = fetch_messages(50)
    lucy_msgs = [m for m in messages if lcd.is_lucy_message(m)]
    print(f"\nFetched {len(messages)} messages, {len(lucy_msgs)} from Lucy (newest first)")

    summary = {"NORMAL": 0, "SUSPICIOUS": 0, "CAPTCHA": 0}
    suspicious_or_captcha = []

    for msg in lucy_msgs:
        result, decision = detector.evaluate_message(msg)
        summary[decision] += 1
        if decision == "NORMAL":
            continue
        suspicious_or_captcha.append((msg, result, decision))
        print("-" * 70)
        print(f"DECISION: {decision}  score={result.risk_score}  high_confidence={result.high_confidence}")
        print(describe_message(msg))
        if result.detected_keywords or result.trigger_reasons:
            print(f"  keywords: {result.detected_keywords}")
            print(f"  reasons : {result.trigger_reasons}")

    print("=" * 70)
    print(f"SUMMARY over {len(lucy_msgs)} Lucy messages:")
    for decision, count in summary.items():
        print(f"  {decision}: {count}")
    if suspicious_or_captcha:
        print(f"\n⚠️ {len(suspicious_or_captcha)} message(s) were NOT NORMAL:")
        for msg, result, decision in suspicious_or_captcha:
            print(f"  - {decision} score={result.risk_score} id={msg.get('id')} "
                  f"reasons={result.trigger_reasons}")
    else:
        print("\n✅ All Lucy messages classified NORMAL — no CAPTCHA indicators found.")


if __name__ == "__main__":
    main()