"""Unit tests for the Lucy CAPTCHA detector (PRD section 20)."""

import pytest  # pyright: ignore[reportMissingImports]

import automation_state
import lucy_captcha_detector as lcd
from lucy_captcha_detector import CaptchaDetector, DetectionResult, DetectionRule

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_message(
    content="",
    embeds=None,
    components=None,
    attachments=None,
    author_id="1438615298012872817",
    name="Lucy",
    bot=True,
    msg_id="111",
    guild_id="222",
    channel_id="333",
):
    return {
        "id": msg_id,
        "guild_id": guild_id,
        "channel_id": channel_id,
        "author": {"id": author_id, "username": name, "bot": bot},
        "content": content,
        "embeds": embeds or [],
        "components": components or [],
        "attachments": attachments or [],
    }


def make_button(label, url=None):
    return {"type": 1, "components": [{"type": 2, "label": label, "url": url}]}


def make_select(placeholder="", options=None):
    return {
        "type": 1,
        "components": [
            {
                "type": 3,
                "placeholder": placeholder,
                "options": [{"label": o} for o in (options or [])],
            }
        ],
    }


def make_embed(title="", description="", fields=None, footer="", author="", url=""):
    embed = {}
    if title:
        embed["title"] = title
    if description:
        embed["description"] = description
    if fields:
        embed["fields"] = [{"name": n, "value": v} for n, v in fields]
    if footer:
        embed["footer"] = {"text": footer}
    if author:
        embed["author"] = {"name": author}
    if url:
        embed["url"] = url
    return embed


@pytest.fixture(autouse=True)
def clean_state():
    automation_state.reset_automation()
    lcd.CONFIG.log_enabled = False  # keep test runs free of log files
    lcd.reset_lucy_monitor()
    yield
    automation_state.reset_automation()


def strict_detector(**kwargs):
    kwargs.setdefault("stop_threshold", 5)
    kwargs.setdefault("monitor_mode", False)
    return CaptchaDetector(**kwargs)


# ---------------------------------------------------------------------------
# PRD Test 1 — Normal Lucy hunt
# ---------------------------------------------------------------------------


def test_normal_hunt_message():
    msg = make_message(
        content="Pai, hunt diperkuat oleh aura kegelapan!\n"
        "Kamu menemukan: Pedang Kegelapan\n"
        "mendapatkan 500xp!"
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "NORMAL"
    assert (
        result.risk_score <= 0
    )  # negative credit for known-normal pattern (NormalPatternRule)
    assert automation_state.bot_running is True


# ---------------------------------------------------------------------------
# PRD Test 2 — Normal battle embed
# ---------------------------------------------------------------------------


def test_normal_battle_embed():
    msg = make_message(
        embeds=[
            make_embed(
                title="Pai bertarung!",
                description="L.19 Musuh\n652 HP 286 WP\n"
                "Tim Musuh\nL.11 Penjaga\n\n"
                "Kamu menang dalam 4 giliran!\nTim kamu mendapat 200 xp!",
            )
        ]
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "NORMAL"
    assert result.risk_score == 0
    assert automation_state.bot_running is True


# ---------------------------------------------------------------------------
# PRD Test 3 — Text CAPTCHA
# ---------------------------------------------------------------------------


def test_text_captcha():
    msg = make_message(content="Please verify that you are human.")
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "CAPTCHA"
    assert result.high_confidence is True
    assert result.risk_score >= 5
    assert "verify that you are human" in result.detected_keywords


# ---------------------------------------------------------------------------
# PRD Test 4 — Button CAPTCHA
# ---------------------------------------------------------------------------


def test_button_captcha():
    msg = make_message(
        content="Verification required",
        components=[make_button("Verify")],
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "CAPTCHA"
    assert result.risk_score >= 5
    assert any(k.startswith("button:") for k in result.detected_keywords)


# ---------------------------------------------------------------------------
# PRD Test 5 — Normal button
# ---------------------------------------------------------------------------


def test_normal_button():
    """Any button from Lucy is suspicious — normal Lucy never uses buttons.

    A non-verification button from Lucy gets score 2 (base) + 1 (interactive)
    = 3, which is SUSPICIOUS (not CAPTCHA) with threshold 5.
    """
    msg = make_message(
        content="Pilih aksi untuk melanjutkan",
        components=[make_button("Next")],
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "SUSPICIOUS"  # not CAPTCHA (score 3 < threshold 5)
    assert automation_state.bot_running is True


# ---------------------------------------------------------------------------
# PRD Test 6 — Attachment normal
# ---------------------------------------------------------------------------


def test_normal_attachment():
    msg = make_message(
        content="Pai, hunt diperkuat oleh aura!",
        attachments=[
            {"filename": "loot.png", "content_type": "image/png", "size": 1234}
        ],
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision != "CAPTCHA"
    assert automation_state.bot_running is True


# ---------------------------------------------------------------------------
# PRD Test 7 — Verification + attachment
# ---------------------------------------------------------------------------


def test_verification_plus_attachment():
    msg = make_message(
        content="Verification required, please check",
        attachments=[
            {"filename": "check.png", "content_type": "image/png", "size": 1234}
        ],
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "CAPTCHA"
    assert result.high_confidence is True
    assert any("attachment" in r for r in result.trigger_reasons)


# ---------------------------------------------------------------------------
# PRD Test 8 — Duplicate CAPTCHA messages (idempotent stop)
# ---------------------------------------------------------------------------


def test_duplicate_captcha_stop_idempotent():
    automation_state.emergency_stop("first captcha")
    automation_state.emergency_stop("second captcha")  # must be a no-op
    assert automation_state.bot_running is False
    assert automation_state.captcha_detected is True
    assert automation_state.stop_reason == "first captcha"

    # Re-analyzing the same CAPTCHA message must not error or change state.
    msg = make_message(content="Please verify that you are human.")
    detector = strict_detector()
    d1 = detector.decide(detector.analyze(msg))
    d2 = detector.decide(detector.analyze(msg))
    assert d1 == d2 == "CAPTCHA"
    assert automation_state.bot_running is False


# ---------------------------------------------------------------------------
# Additional coverage
# ---------------------------------------------------------------------------


def test_embed_captcha_title_and_description():
    msg = make_message(
        embeds=[
            make_embed(
                title="Verification Required",
                description="Please verify that you are human",
            )
        ]
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "CAPTCHA"
    assert result.high_confidence is True


def test_select_menu_captcha():
    msg = make_message(
        content="Verification required",
        components=[make_select("Select verification method", ["Verify", "Email"])],
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "CAPTCHA"
    assert result.risk_score >= 5


def test_verification_url():
    msg = make_message(
        content="Please verify here",
        embeds=[make_embed(url="https://verify.example.com/challenge/abc")],
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "CAPTCHA"
    assert "verification-url" in result.detected_keywords


def test_single_verify_word_is_not_enough_alone():
    msg = make_message(content="verify")
    result, decision = strict_detector().evaluate_message(msg)
    assert decision != "CAPTCHA"
    assert result.risk_score < 5


def test_challenge_keyword_alone_is_weak():
    msg = make_message(content="challenge")
    result, decision = strict_detector().evaluate_message(msg)
    assert decision != "CAPTCHA"


def test_monitor_mode_flags_but_does_not_stop():
    detector = CaptchaDetector(stop_threshold=5, monitor_mode=True)
    # "security check" (+3) + "verify" (+2) = 5, no high-confidence combo.
    msg = make_message(content="security check verify")
    result, decision = detector.evaluate_message(msg)
    assert decision == "SUSPICIOUS"
    assert automation_state.bot_running is True


def test_monitor_mode_still_stops_on_high_confidence():
    detector = CaptchaDetector(stop_threshold=5, monitor_mode=True)
    msg = make_message(content="Please verify that you are human.")
    result, decision = detector.evaluate_message(msg)
    assert decision == "CAPTCHA"


def test_configurable_threshold():
    detector = CaptchaDetector(stop_threshold=8, monitor_mode=False)
    msg = make_message(content="security check verify")  # score 5
    result, decision = detector.evaluate_message(msg)
    assert decision == "SUSPICIOUS"


def test_is_lucy_message_by_id():
    msg = make_message(author_id="1438615298012872817")
    assert lcd.is_lucy_message(msg, lucy_bot_id="1438615298012872817") is True
    assert lcd.is_lucy_message(msg, lucy_bot_id="999999999999999999") is False


def test_is_lucy_message_fallback_name():
    msg = make_message(author_id="123", name="lucy", bot=True)
    assert lcd.is_lucy_message(msg, lucy_bot_id="") is True
    msg2 = make_message(author_id="123", name="notlucy", bot=True)
    assert lcd.is_lucy_message(msg2, lucy_bot_id="") is False
    msg3 = make_message(author_id="123", name="Lucy", bot=False)
    assert lcd.is_lucy_message(msg3, lucy_bot_id="") is False


def test_informational_components_not_flagged():
    # Lucy's normal leaderboard/profile replies carry pagination/media/rich
    # components (types 9/10/14) — these must NOT raise the risk score.
    msg = make_message(
        components=[
            {
                "type": 1,
                "components": [
                    {"type": 10},
                    {"type": 14},
                    {"type": 9},
                    {"type": 14},
                    {"type": 9},
                    {"type": 10},
                ],
            }
        ]
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "NORMAL"
    assert result.risk_score == 0


# ---------------------------------------------------------------------------
# Live-data based tests (from 51 messages, 20 cycles)
# ---------------------------------------------------------------------------


def test_normal_pet_capture_common():
    """Normal Lucy pet capture — common tier (16 occurrences in live data)."""
    msg = make_message(
        content="**🌱 | Pai** menghabiskan 5 <:lucent:1523362382355759266>**common** <:common:1521986808169369700> dan menangkap :snail:!\n"
        "<:blank:1522595651571941560> **|** <:ghost_busted:1545620171413127259> mendapatkan **1xp**!\n"
        "**<:lootbox:1521954608828907550>|** Kamu menemukan **lootbox**! `[1/3] RESET DALAM: 22H 53M 29S`"
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "NORMAL"
    assert result.risk_score <= 0


def test_normal_weapon_crate():
    """Normal Lucy weapon crate find (3 occurrences in live data)."""
    msg = make_message(
        content="**<:crate:1521955001101058210> | Pai**, Kamu menemukan **weapon crate**! `[1/3] RESET DALAM: 22J 53M 27D`"
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "NORMAL"
    assert result.risk_score <= 0


def test_normal_battle_result_with_wrapper_components():
    """Normal Lucy battle result using Wrapper > Container > TextDisplay + Separator."""
    msg = make_message(
        components=[
            {
                "type": 17,
                "id": 1,
                "accent_color": 65280,
                "components": [
                    {
                        "type": 9,
                        "id": 2,
                        "components": [
                            {"type": 10, "id": 3, "content": "## Pai bertarung!"}
                        ],
                        "accessory": {"type": 11},
                    },
                    {"type": 14, "id": 5, "spacing": 1, "divider": True},
                    {"type": 10, "id": 6, "content": "Team info here"},
                    {"type": 14, "id": 7, "spacing": 1, "divider": True},
                    {
                        "type": 10,
                        "id": 8,
                        "content": "-# Kamu menang dalam 3 giliran! Tim kamu mendapat 200 xp!",
                    },
                ],
            }
        ]
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "NORMAL"
    assert result.risk_score <= 0


def test_any_button_from_lucy_is_suspicious():
    """Normal Lucy NEVER uses buttons (0 buttons in 51 live messages).
    Any button should trigger at least SUSPICIOUS."""
    msg = make_message(
        content="Something",
        components=[{"type": 1, "components": [{"type": 2, "label": "Next"}]}],
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision in ("SUSPICIOUS", "CAPTCHA")
    assert result.risk_score >= 2


def test_verification_button_is_high_confidence():
    """Button with verification label is high confidence CAPTCHA."""
    msg = make_message(
        content="",
        components=[{"type": 1, "components": [{"type": 2, "label": "Verify"}]}],
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "CAPTCHA"
    assert result.high_confidence is True


def test_any_select_menu_from_lucy_is_suspicious():
    """Normal Lucy NEVER uses select menus. Any should trigger."""
    msg = make_message(
        content="Something",
        components=[
            {
                "type": 1,
                "components": [
                    {
                        "type": 3,
                        "placeholder": "Choose action",
                        "options": [{"label": "A"}, {"label": "B"}],
                    }
                ],
            }
        ],
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision in ("SUSPICIOUS", "CAPTCHA")


def test_empty_content_with_button_is_very_suspicious():
    """Empty content + button = bare interactive component, very suspicious."""
    msg = make_message(
        content="",
        components=[{"type": 1, "components": [{"type": 2, "label": "Continue"}]}],
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert result.risk_score >= 3
    assert any("bare" in r or "interactive" in r for r in result.trigger_reasons)


def test_normal_pet_capture_rare():
    """Normal Lucy pet capture — rare tier."""
    msg = make_message(
        content="**🌱 | Pai** menghabiskan 5 <:lucent:1523362382355759266>**rare** <:rare:1521986845213458482> dan menangkap :unicorn:!\n"
        "<:blank:1522595651571941560> **|** mendapatkan **3xp**!"
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "NORMAL"


def test_combo_button_plus_verify_keyword():
    """Button + verify keyword = strong combo signal."""
    msg = make_message(
        content="Please verify",
        components=[{"type": 1, "components": [{"type": 2, "label": "Click here"}]}],
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "CAPTCHA"
    assert result.high_confidence is True


def test_normal_hunt_with_emoji_and_fields():
    # Live Lucy hunt reply (PRD section 16): heavy emoji usage, no embeds.
    msg = make_message(
        content="**🌱 | Pai**, hunt diperkuat oleh <:egem1:1521963195240022037>`[13/75]` !\n"
        "**<:blank:1522595651571941560> |** Kamu menemukan: :bee: :bee: :beetle:\n"
        "<:blank:1522595651571941560> **|** <:ghost_busted:1545620171413127259> mendapatkan **2xp**!"
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "NORMAL"
    assert result.risk_score == 0


def test_normal_battle_embed_with_emoji_fields():
    # Live Lucy battle embed (PRD section 16): emoji-heavy fields, no keywords.
    msg = make_message(
        embeds=[
            make_embed(
                fields=[
                    (
                        "དℭ℟Åℤ¥༒₭ÏḼḼ℥℟ཌ",
                        "L.19 - <:epic:1521986864444084224><:peestaff:1541868074553311313>",
                    ),
                    (
                        "Tim Musuh",
                        "L.14 - <:rare:1521986845213458482>\n`0 HP` `556 WP`",
                    ),
                ],
                footer="Kamu menang dalam 5 giliran! Tim kamu mendapat 200 xp! Beruntun: 146",
                author="Pai bertarung!",
            )
        ]
    )
    result, decision = strict_detector().evaluate_message(msg)
    assert decision == "NORMAL"
    assert result.risk_score == 0


def test_rule_extensibility():
    class AlwaysSuspiciousRule(DetectionRule):
        name = "AlwaysSuspiciousRule"

        def evaluate(self, message):
            r = DetectionResult()
            r.risk_score += 10
            r.trigger_reasons.append("custom rule triggered")
            return r

    detector = CaptchaDetector(
        rules=[AlwaysSuspiciousRule()], stop_threshold=5, monitor_mode=False
    )
    result, decision = detector.evaluate_message(make_message(content="normal text"))
    assert decision == "CAPTCHA"
    assert result.risk_score == 10


def test_reset_automation():
    automation_state.emergency_stop("test stop")
    assert automation_state.bot_running is False
    automation_state.reset_automation()
    assert automation_state.bot_running is True
    assert automation_state.captcha_detected is False


def test_log_incident_writes_expected_fields(tmp_path):
    lcd.CONFIG.log_enabled = True
    lcd.CONFIG.log_file = str(tmp_path / "captcha.log")
    msg = make_message(
        content="Verification required",
        components=[make_button("Verify")],
        attachments=[{"filename": "x.png", "content_type": "image/png"}],
    )
    detector = strict_detector()
    result = detector.analyze(msg)
    lcd.log_incident(msg, result, "STOP BOT")
    text = (tmp_path / "captcha.log").read_text(encoding="utf-8")
    assert "CAPTCHA DETECTOR" in text
    assert "risk_score" in text
    assert "reasons" in text
    assert "action" in text
    assert "STOP BOT" in text
    lcd.CONFIG.log_enabled = False
