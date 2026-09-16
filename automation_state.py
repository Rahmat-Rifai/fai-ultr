"""Central automation state and emergency stop (PRD sections 12-15).

Every loop (command loop, spam loop, scheduled tasks, retry loop, queue
worker) must check ``automation_state.bot_running`` before doing work or
sending a new command. When a high-confidence CAPTCHA is detected,
``emergency_stop()`` flips the state so all loops stop.

The stop is idempotent: calling ``emergency_stop()`` multiple times only
performs the stop sequence once. ``reset_automation()`` is a manual reset
and is never performed automatically.
"""

from datetime import datetime

bot_running = True
captcha_detected = False
_stopped = False
stop_reason = None


def emergency_stop(reason: str):
    """Stop all automation. Safe to call multiple times (idempotent)."""
    global bot_running, captcha_detected, _stopped, stop_reason

    if _stopped:
        return

    _stopped = True
    bot_running = False
    captcha_detected = True
    stop_reason = reason

    print("\n" + "=" * 50)
    print("⚠️ CAPTCHA / ANTI-BOT DETECTED")
    print(f"Reason: {reason}")
    print("🛑 AUTOMATION STOPPED")
    print("=" * 50)

    try:
        with open("rpg_cycles.log", "a") as f:
            f.write(f"\nAUTOMATION STOPPED at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: {reason}\n")
    except Exception:
        pass


def reset_automation():
    """Manually reset automation after the CAPTCHA has been handled.

    Never called automatically — only by a human operator.
    """
    global bot_running, captcha_detected, _stopped, stop_reason

    bot_running = True
    captcha_detected = False
    _stopped = False
    stop_reason = None

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Automation reset (manual)")