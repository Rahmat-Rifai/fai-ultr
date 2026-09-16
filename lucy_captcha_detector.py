"""Lucy CAPTCHA Detector (PRD)

Detects suspicious / CAPTCHA-like messages sent by the Lucy bot using an
extensible rule pipeline + risk scoring. When a message is high confidence
(or the risk score crosses the configured threshold outside monitor mode),
all automation is stopped via ``automation_state.emergency_stop()``.

Design goals from the PRD:
- Generic detection, NOT a guess at Lucy's real CAPTCHA format.
- Rules are modular: add a new rule class without touching command logic.
- Never solves, bypasses, clicks or fetches a CAPTCHA.

The detector works on raw Discord REST API message dicts so it can be unit
tested without network access.
"""

import os
import re
from dataclasses import dataclass, field
from datetime import datetime

import automation_state  # noqa: I001

# ---------------------------------------------------------------------------
# Configuration (PRD section 18)
# ---------------------------------------------------------------------------


def _env_bool(name, default):
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class Config:
    def __init__(self):
        self.lucy_bot_id = (os.getenv("LUCY_BOT_ID") or "").strip()
        self.detection_enabled = _env_bool("CAPTCHA_DETECTION_ENABLED", True)
        self.stop_threshold = _env_int("CAPTCHA_STOP_THRESHOLD", 5)
        self.monitor_mode = _env_bool("CAPTCHA_MONITOR_MODE", True)
        self.log_enabled = _env_bool("CAPTCHA_LOG_ENABLED", True)
        self.log_normal = _env_bool("CAPTCHA_LOG_NORMAL", False)
        self.log_file = os.getenv("CAPTCHA_LOG_FILE", "lucy_captcha_log.txt")


CONFIG = Config()


# ---------------------------------------------------------------------------
# Data types (PRD section 7 / 17)
# ---------------------------------------------------------------------------


@dataclass
class DetectionResult:
    risk_score: int = 0
    detected_keywords: list = field(default_factory=list)
    trigger_reasons: list = field(default_factory=list)
    high_confidence: bool = False


class DetectionRule:
    name = "base"

    def evaluate(self, message) -> DetectionResult:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Message helpers (Discord REST API message dict)
# ---------------------------------------------------------------------------


def _iter_components(message):
    for row in message.get("components") or []:
        yield from (row.get("components") or [])


def _embed_texts(message):
    texts = []
    for embed in message.get("embeds") or []:
        for key in ("title", "description"):
            if embed.get(key):
                texts.append(str(embed[key]))
        for f in embed.get("fields") or []:
            if f.get("name"):
                texts.append(str(f["name"]))
            if f.get("value"):
                texts.append(str(f["value"]))
        if embed.get("footer") and embed["footer"].get("text"):
            texts.append(str(embed["footer"]["text"]))
        if embed.get("author") and embed["author"].get("name"):
            texts.append(str(embed["author"]["name"]))
    return texts


def _all_text(message):
    parts = []
    if message.get("content"):
        parts.append(str(message["content"]))
    parts.extend(_embed_texts(message))
    return "\n".join(parts)


def _all_urls(message):
    urls = []
    content = message.get("content") or ""
    urls.extend(re.findall(r"https?://[^\s<>\"']+", content))
    for embed in message.get("embeds") or []:
        if embed.get("url"):
            urls.append(embed["url"])
        if embed.get("author") and embed["author"].get("url"):
            urls.append(embed["author"]["url"])
        if embed.get("footer") and embed["footer"].get("url"):
            urls.append(embed["footer"]["url"])
    for comp in _iter_components(message):
        if comp.get("type") == 2 and comp.get("url"):
            urls.append(comp["url"])
    return urls


# ---------------------------------------------------------------------------
# Keywords (PRD section 6.1 / 7)
# ---------------------------------------------------------------------------

KEYWORDS = [
    # (pattern, score, high_confidence, word_boundary)
    # --- Tier 1: Definite CAPTCHA (score 5, high_confidence) ---
    ("verify that you are human", 5, True, False),
    ("verify you are human", 5, True, False),
    ("prove you are human", 5, True, False),
    ("verify you're human", 5, True, False),
    ("prove you're human", 5, True, False),
    ("human verification", 5, True, False),
    ("captcha", 5, True, False),
    ("click to verify", 5, True, False),
    ("click here to verify", 5, True, False),
    ("i'm not a robot", 5, True, False),
    ("im not a robot", 5, True, False),
    # --- Tier 2: Strong CAPTCHA indicators (score 4) ---
    ("are you human", 4, False, False),
    ("i am not a robot", 4, False, False),
    ("not a robot", 4, False, False),
    ("verification required", 4, False, False),
    ("verification needed", 4, False, False),
    ("complete verification", 4, False, False),
    ("verify your identity", 4, False, False),
    ("select all images", 4, False, False),
    ("click the squares", 4, False, False),
    ("click all squares", 4, False, False),
    ("solve the captcha", 4, False, False),
    ("solve this puzzle", 4, False, False),
    ("prove you're not a bot", 4, False, False),
    # --- Tier 3: Moderate indicators (score 3) ---
    ("security check", 3, False, False),
    ("security verification", 3, False, False),
    ("anti-bot", 3, False, False),
    ("anti bot", 3, False, False),
    ("bot detection", 3, False, False),
    ("suspicious activity", 3, False, False),
    ("unusual activity", 3, False, False),
    ("are you a bot", 3, False, False),
    ("prove humanity", 3, False, False),
    ("humanity check", 3, False, False),
    # --- Tier 4: Weak standalone (score 1-2, word boundary) ---
    # Only trigger when combined with other signals (ComboRule / ButtonRule)
    ("verification", 2, False, True),
    ("verify", 2, False, True),
    ("robot", 2, False, True),
    ("human", 1, False, True),
    ("challenge", 1, False, True),  # boosted to +3 in verification context (ComboRule)
]


def _scan_keywords(text):
    """Return non-overlapping (keyword, score, high_confidence) matches."""
    if not text:
        return []
    text_lower = text.lower()
    matches = []  # (start, end, label, score, high)
    for pattern, score, high, boundary in KEYWORDS:
        regex = (r"\b" + re.escape(pattern) + r"\b") if boundary else re.escape(pattern)
        for m in re.finditer(regex, text_lower):
            matches.append((m.start(), m.end(), pattern, score, high))
    # Prefer stronger/longer matches; drop overlapping weaker ones.
    matches.sort(key=lambda m: (-m[3], -(m[1] - m[0])))
    picked = []
    for start, end, label, score, high in matches:
        if any(start < p_end and p_start < end for p_start, p_end, *_ in picked):
            continue
        picked.append((start, end, label, score, high))
    picked.sort(key=lambda m: m[0])
    return [(label, score, high) for _, _, label, score, high in picked]


# ---------------------------------------------------------------------------
# Rules (PRD section 17)
# ---------------------------------------------------------------------------


class KeywordRule(DetectionRule):
    """Plain text / message content keywords (PRD 6.1)."""

    name = "KeywordRule"

    def evaluate(self, message):
        result = DetectionResult()
        for label, score, high in _scan_keywords(message.get("content") or ""):
            result.risk_score += score
            result.detected_keywords.append(label)
            result.trigger_reasons.append(f'keyword "{label}" detected')
            if high:
                result.high_confidence = True
        return result


class EmbedRule(DetectionRule):
    """Embed title/description/fields/footer/author analysis (PRD 6.2)."""

    name = "EmbedRule"

    def evaluate(self, message):
        result = DetectionResult()
        embed_texts = _embed_texts(message)
        if not embed_texts:
            return result
        found = _scan_keywords("\n".join(embed_texts))
        for label, score, high in found:
            result.risk_score += score
            result.detected_keywords.append(label)
            result.trigger_reasons.append(f'keyword "{label}" in embed')
            if high:
                result.high_confidence = True
        if found:
            result.risk_score += min(len(found), 2)
        return result


BUTTON_KEYWORDS = (
    "verify",
    "verification",
    "captcha",
    "human",
    "security",
    "challenge",
    "prove",
)


class ButtonRule(DetectionRule):
    """Any button from Lucy is suspicious — normal Lucy never uses buttons.

    Based on live data (51 messages, 20 cycles):
    - Normal Lucy responses NEVER contain buttons (type 2)
    - CAPTCHA messages typically include a "Verify" or similar button
    - Even a non-verification button from Lucy is a format anomaly
    """

    name = "ButtonRule"

    def evaluate(self, message):
        result = DetectionResult()
        score = 0
        for comp in _iter_components(message):
            if comp.get("type") != 2:
                continue
            label = (comp.get("label") or "").strip()
            label_lower = label.lower()
            # Any button from Lucy is suspicious — none in normal data
            score += 2  # base score for any button
            if label_lower and any(kw in label_lower for kw in BUTTON_KEYWORDS):
                score += 3  # extra for verification-related label
                result.detected_keywords.append(f"button:{label}")
                result.trigger_reasons.append(f'verification button "{label}" detected')
                result.high_confidence = True
            elif label_lower:
                result.detected_keywords.append(f"button:{label}")
                result.trigger_reasons.append(f'unexpected button "{label}" from Lucy')
        result.risk_score += min(score, 6)
        return result


SELECT_KEYWORDS = (
    "verify",
    "verification",
    "captcha",
    "human",
    "security",
    "challenge",
)


class SelectRule(DetectionRule):
    """Any select menu from Lucy is suspicious — normal Lucy never uses them.

    Based on live data: normal Lucy responses only use informational
    components (Text Display, Separator, Container, Wrapper).
    """

    name = "SelectRule"

    def evaluate(self, message):
        result = DetectionResult()
        score = 0
        for comp in _iter_components(message):
            if comp.get("type") != 3:
                continue
            texts = []
            if comp.get("placeholder"):
                texts.append(str(comp["placeholder"]))
            for opt in comp.get("options") or []:
                if opt.get("label"):
                    texts.append(str(opt["label"]))
            combined = " ".join(texts).lower()
            # Any select menu from Lucy is suspicious
            score += 2
            if any(kw in combined for kw in SELECT_KEYWORDS):
                score += 3
                result.detected_keywords.append("select-menu")
                result.trigger_reasons.append("verification select menu detected")
            else:
                result.detected_keywords.append("select-menu")
                result.trigger_reasons.append("unexpected select menu from Lucy")
        result.risk_score += min(score, 6)
        return result


ATTACHMENT_KEYWORDS = ("captcha", "verif", "human", "challenge", "robot")


class AttachmentRule(DetectionRule):
    """Attachments: never enough alone, but suspicious names add risk (PRD 6.4)."""

    name = "AttachmentRule"

    def evaluate(self, message):
        result = DetectionResult()
        attachments = message.get("attachments") or []
        if not attachments:
            return result
        suspicious = False
        for att in attachments:
            meta = (
                f"{att.get('filename') or ''} {att.get('content_type') or ''}".lower()
            )
            if any(kw in meta for kw in ATTACHMENT_KEYWORDS):
                suspicious = True
                result.detected_keywords.append(f"attachment:{att.get('filename')}")
                result.trigger_reasons.append(
                    f"suspicious attachment: {att.get('filename')}"
                )
        if suspicious:
            result.risk_score += 2
        return result


URL_KEYWORDS = (
    "verify",
    "verification",
    "captcha",
    "hcaptcha",
    "recaptcha",
    "human",
    "challenge",
    "security",
    "anti-bot",
    "antibot",
)


class UrlRule(DetectionRule):
    """URLs related to verification/challenge (PRD 6.5). Never fetched."""

    name = "UrlRule"

    def evaluate(self, message):
        result = DetectionResult()
        for url in _all_urls(message):
            low = url.lower()
            if any(kw in low for kw in URL_KEYWORDS):
                result.risk_score += 3
                result.detected_keywords.append("verification-url")
                result.trigger_reasons.append(f"verification-related URL: {url[:80]}")
                break  # one indicator is enough
        return result


class NormalPatternRule(DetectionRule):
    """Recognize known-normal Lucy response patterns (negative risk score).

    Based on 51 live messages (20 cycles), normal Lucy responses are:
    1. Pet captures: "🌱 | Pai" + lucent spending + pet name
    2. Weapon crates: "crate emoji | Pai" + "weapon crate"
    3. Battle results: Wrapper(17) > Container(9) > TextDisplay(10) + Separator(14)
    4. Hunt results: emoji-heavy text about finding items/xp

    These patterns are strong evidence of normal activity and should
    reduce false positives by providing negative risk score credit.
    """

    name = "NormalPatternRule"

    # Compiled patterns for common normal Lucy messages
    _NORMAL_CONTENT_PATTERNS = [
        re.compile(r"🌱\s*\|\s*\w+.*menghabiskan\s+\d+\s+.*lucent", re.IGNORECASE),
        re.compile(r"weapon\s+crate", re.IGNORECASE),
        re.compile(r"lootbox", re.IGNORECASE),
        re.compile(r"menangkap\s+:", re.IGNORECASE),
        re.compile(r"mendapatkan\s+\d+xp", re.IGNORECASE),
        re.compile(r"RESET\s+DALAM:", re.IGNORECASE),
    ]

    def evaluate(self, message):
        result = DetectionResult()
        content = message.get("content") or ""

        # Check if this matches a known normal content pattern
        for pattern in self._NORMAL_CONTENT_PATTERNS:
            if pattern.search(content):
                result.risk_score -= 2
                result.trigger_reasons.append("matches known normal Lucy pattern")
                break

        # Battle results use Wrapper > Container > TextDisplay + Separator
        # with NO buttons/selects — strong normal indicator
        components = message.get("components") or []
        has_wrapper = any(c.get("type") == 17 for c in components)
        if has_wrapper:
            all_comps = []
            for row in components:
                all_comps.extend(row.get("components") or [])
            has_text_display = any(c.get("type") == 10 for c in all_comps)
            has_separator = any(c.get("type") == 14 for c in all_comps)
            has_interactive = any(c.get("type") in (2, 3) for c in all_comps)
            if has_text_display and has_separator and not has_interactive:
                result.risk_score -= 3
                result.trigger_reasons.append(
                    "Wrapper > Container > TextDisplay + Separator (normal battle)"
                )

        return result


class PatternRule(DetectionRule):
    """Message format very different from Lucy's normal responses (PRD 7).

    Based on live data analysis:
    - Normal Lucy NEVER uses buttons (type 2) or select menus (type 3)
    - Normal Lucy ONLY uses informational components: Text Display (10),
      Separator (14), Container (9), Wrapper (17)
    - Any interactive component is a strong CAPTCHA indicator
    """

    name = "PatternRule"

    def evaluate(self, message):
        result = DetectionResult()
        content = (message.get("content") or "").strip()
        embeds = message.get("embeds") or []
        interactive = [c for c in _iter_components(message) if c.get("type") in (2, 3)]
        # Any interactive component (button/select) from Lucy is anomalous
        if interactive:
            result.risk_score += 2
            result.trigger_reasons.append(
                f"interactive component(s) type {[c.get('type') for c in interactive]} "
                f"— Lucy never uses buttons/selects normally"
            )
            # Bare interactive control with no text is very suspicious
            if len(content) < 5 and not embeds:
                result.risk_score += 1
                result.trigger_reasons.append(
                    "bare interactive component with minimal text"
                )
        return result


class ComboRule(DetectionRule):
    """High-confidence combinations (PRD section 8 / 19).

    Based on live data: normal Lucy messages never contain both a keyword
    AND an interactive component. The combination is a very strong signal.
    """

    name = "ComboRule"

    def evaluate(self, message):
        result = DetectionResult()
        text = _all_text(message).lower()
        comps = list(_iter_components(message))
        has_button = any(c.get("type") == 2 for c in comps)
        has_select = any(c.get("type") == 3 for c in comps)
        has_interactive = has_button or has_select
        has_attachment = bool(message.get("attachments"))
        has_human = "human" in text
        # Verification-family words (bare "human" alone is too weak a trigger).
        has_verification = any(
            w in text
            for w in (
                "verify",
                "verification",
                "captcha",
                "security check",
                "human verification",
                "prove",
                "challenge",
            )
        )
        has_verification_url = any(
            kw in url.lower() for url in _all_urls(message) for kw in URL_KEYWORDS
        )

        # --- High-confidence combos (immediate CAPTCHA) ---
        if has_verification and has_interactive:
            result.high_confidence = True
            result.trigger_reasons.append(
                "combo: verification keyword + interactive component"
            )
        if has_verification and has_attachment:
            result.high_confidence = True
            result.trigger_reasons.append("combo: verification keyword + attachment")
        if has_verification and has_verification_url:
            result.high_confidence = True
            result.trigger_reasons.append(
                "combo: verification keyword + verification URL"
            )
        if has_verification and has_human:
            result.high_confidence = True
            result.trigger_reasons.append("combo: verification + human")
        if "challenge" in text and (has_verification or has_human):
            result.risk_score += 2
            result.trigger_reasons.append("challenge in verification context")

        # --- Strong combos (high score, may trigger threshold) ---
        # Any button + any verification keyword is almost certainly CAPTCHA
        if has_button and any(
            w in text for w in ("verify", "captcha", "prove", "human")
        ):
            result.risk_score += 3
            result.trigger_reasons.append("button + verification keyword")

        # "Click to verify" / "Click here" + any interactive component
        if has_interactive and any(w in text for w in ("click", "tap", "press")):
            result.risk_score += 3
            result.trigger_reasons.append(
                "click-action keyword + interactive component"
            )

        return result


def default_rules():
    return [
        KeywordRule(),
        EmbedRule(),
        ButtonRule(),
        SelectRule(),
        AttachmentRule(),
        UrlRule(),
        NormalPatternRule(),  # Negative score for known-normal patterns
        PatternRule(),
        ComboRule(),
    ]


class CaptchaDetector:
    """Runs all rules on a message and decides what to do."""

    def __init__(self, rules=None, stop_threshold=None, monitor_mode=None):
        self.rules = rules if rules is not None else default_rules()
        self.stop_threshold = (
            stop_threshold if stop_threshold is not None else CONFIG.stop_threshold
        )
        self.monitor_mode = (
            monitor_mode if monitor_mode is not None else CONFIG.monitor_mode
        )

    def analyze(self, message) -> DetectionResult:
        result = DetectionResult()
        for rule in self.rules:
            r = rule.evaluate(message)
            result.risk_score += r.risk_score
            result.detected_keywords.extend(r.detected_keywords)
            result.trigger_reasons.extend(r.trigger_reasons)
            result.high_confidence = result.high_confidence or r.high_confidence
        result.detected_keywords = list(dict.fromkeys(result.detected_keywords))
        result.trigger_reasons = list(dict.fromkeys(result.trigger_reasons))
        return result

    def decide(self, result: DetectionResult) -> str:
        """Return NORMAL, SUSPICIOUS (log only) or CAPTCHA (stop)."""
        if result.high_confidence:
            return "CAPTCHA"
        if result.risk_score >= self.stop_threshold:
            return "SUSPICIOUS" if self.monitor_mode else "CAPTCHA"
        if result.risk_score > 0:
            return "SUSPICIOUS"
        return "NORMAL"

    def evaluate_message(self, message):
        result = self.analyze(message)
        return result, self.decide(result)


# ---------------------------------------------------------------------------
# Lucy identification (PRD section 4)
# ---------------------------------------------------------------------------


def is_lucy_message(message, lucy_bot_id=None):
    """True if the message author is the Lucy bot.

    Primary: bot user ID (LUCY_BOT_ID). Fallback: bot flag + name "Lucy".
    """
    lucy_bot_id = (lucy_bot_id if lucy_bot_id is not None else CONFIG.lucy_bot_id) or ""
    author = message.get("author") or {}
    author_id = str(author.get("id") or "")
    if lucy_bot_id:
        return author_id == str(lucy_bot_id)
    name = (
        author.get("username")
        or author.get("display_name")
        or author.get("global_name")
        or ""
    ).lower()
    return bool(author.get("bot")) and name == "lucy"


# ---------------------------------------------------------------------------
# Logging (PRD section 10 / 11)
# ---------------------------------------------------------------------------


def log_incident(message, result, action):
    if not CONFIG.log_enabled:
        return
    author = message.get("author") or {}

    embed_data = []
    for embed in message.get("embeds") or []:
        entry = {}
        for k in ("title", "description", "url"):
            if embed.get(k):
                entry[k] = str(embed[k])[:200]
        if embed.get("fields"):
            entry["fields"] = [
                {"name": f.get("name"), "value": str(f.get("value"))[:200]}
                for f in embed["fields"]
            ]
        if embed.get("footer") and embed["footer"].get("text"):
            entry["footer"] = embed["footer"]["text"]
        if embed.get("author") and embed["author"].get("name"):
            entry["author"] = embed["author"]["name"]
        embed_data.append(entry)

    component_data = []
    for comp in _iter_components(message):
        entry = {"type": comp.get("type")}
        if comp.get("label"):
            entry["label"] = comp["label"]
        if comp.get("placeholder"):
            entry["placeholder"] = comp["placeholder"]
        if comp.get("url"):
            entry["url"] = comp["url"]
        component_data.append(entry)

    attachment_metadata = [
        {
            "filename": a.get("filename"),
            "content_type": a.get("content_type"),
            "size": a.get("size"),
        }
        for a in (message.get("attachments") or [])
    ]

    lines = [
        "=" * 60,
        "[CAPTCHA DETECTOR]",
        f"timestamp    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"guild_id     : {message.get('guild_id')}",
        f"channel_id   : {message.get('channel_id')}",
        f"message_id   : {message.get('id')}",
        f"author_id    : {author.get('id')}",
        f"author_name  : {author.get('username') or author.get('display_name')}",
        f"content      : {(message.get('content') or '')[:500]}",
        f"embed_count  : {len(message.get('embeds') or [])}",
        f"embed_data   : {embed_data}",
        f"component_count: {len(list(_iter_components(message)))}",
        f"component_data: {component_data}",
        f"attachment_count: {len(message.get('attachments') or [])}",
        f"attachment_metadata: {attachment_metadata}",
        f"keywords     : {result.detected_keywords}",
        f"risk_score   : {result.risk_score}",
        f"reasons      : {result.trigger_reasons}",
        f"action       : {action}",
        "=" * 60,
        "",
    ]
    try:
        with open(CONFIG.log_file, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        print(f"[CAPTCHA DETECTOR] Log write failed: {e}")


# ---------------------------------------------------------------------------
# Monitor (PRD section 9 / 21)
# ---------------------------------------------------------------------------

_seen_message_ids = set()
_MAX_SEEN = 1000


def check_lucy_captcha(headers, channel_id, detector=None, limit=20):
    """Fetch recent channel messages, analyze Lucy's, stop/flags as needed.

    Returns True if automation was stopped (or is already stopped).
    """
    if not CONFIG.detection_enabled:
        return False
    if not automation_state.bot_running:
        return True

    detector = detector or CaptchaDetector()

    try:
        import requests  # lazy import so the detector stays unit-testable offline

        url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit={limit}"
        response = requests.get(url, headers=headers, verify=False, timeout=30)  # noqa: S501
        if response.status_code != 200:
            return False
        messages = response.json()
    except Exception as e:
        print(f"[CAPTCHA DETECTOR] Error fetching messages: {e}")
        return False

    stopped = False
    for msg in messages:
        if not is_lucy_message(msg):
            continue
        msg_id = msg.get("id")
        if msg_id in _seen_message_ids:
            continue
        _seen_message_ids.add(msg_id)
        if len(_seen_message_ids) > _MAX_SEEN:
            _seen_message_ids.clear()

        result, decision = detector.evaluate_message(msg)

        if decision == "NORMAL":
            if CONFIG.log_normal:
                print("[LUCY] Normal response")
            continue

        action = "STOP BOT" if decision == "CAPTCHA" else "FLAGGED ONLY"
        if decision == "CAPTCHA":
            print(f"[LUCY] CAPTCHA detected — score {result.risk_score}")
        else:
            print(f"[LUCY] Suspicious response — score {result.risk_score}")

        log_incident(msg, result, action)

        if decision == "CAPTCHA":
            reasons = "; ".join(result.trigger_reasons)
            automation_state.emergency_stop(
                f"Lucy CAPTCHA (score {result.risk_score}): {reasons}"
            )
            stopped = True
            break

    return stopped or not automation_state.bot_running


def reset_lucy_monitor():
    """Forget processed message IDs (used with manual reset)."""
    _seen_message_ids.clear()
