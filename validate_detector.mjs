/**
 * Validate lucy_captcha_detector logic against live-collected data.
 * Loads lucy_collect.jsonl and runs the same detection rules as the Python
 * detector to verify all 51 messages are classified NORMAL, and that
 * synthetic CAPTCHA messages are correctly detected.
 */
import fs from "fs";

// --- Regex patterns matching lucy_captcha_detector.py NormalPatternRule ---
const NORMAL_PATTERNS = [
  /🌱\s*\|\s*\w+.*menghabiskan\s+\d+\s+.*lucent/i,
  /weapon\s+crate/i,
  /lootbox/i,
  /menangkap\s+:/i,
  /mendapatkan\s+\d+xp/i,
  /RESET\s+DALAM:/i,
];

// --- Keywords matching KEYWORDS in lucy_captcha_detector.py ---
const KEYWORDS = [
  ["verify that you are human", 5, true],
  ["verify you are human", 5, true],
  ["prove you are human", 5, true],
  ["verify you're human", 5, true],
  ["prove you're human", 5, true],
  ["human verification", 5, true],
  ["captcha", 5, true],
  ["click to verify", 5, true],
  ["click here to verify", 5, true],
  ["i'm not a robot", 5, true],
  ["im not a robot", 5, true],
  ["are you human", 4, false],
  ["i am not a robot", 4, false],
  ["not a robot", 4, false],
  ["verification required", 4, false],
  ["verification needed", 4, false],
  ["complete verification", 4, false],
  ["verify your identity", 4, false],
  ["select all images", 4, false],
  ["click the squares", 4, false],
  ["click all squares", 4, false],
  ["solve the captcha", 4, false],
  ["solve this puzzle", 4, false],
  ["prove you're not a bot", 4, false],
  ["security check", 3, false],
  ["security verification", 3, false],
  ["anti-bot", 3, false],
  ["anti bot", 3, false],
  ["bot detection", 3, false],
  ["suspicious activity", 3, false],
  ["unusual activity", 3, false],
  ["are you a bot", 3, false],
  ["prove humanity", 3, false],
  ["humanity check", 3, false],
  ["verification", 2, false],
  ["verify", 2, false],
  ["robot", 2, false],
  ["human", 1, false],
  ["challenge", 1, false],
];

const BUTTON_KEYWORDS = ["verify","verification","captcha","human","security","challenge","prove"];
const SELECT_KEYWORDS = ["verify","verification","captcha","human","security","challenge"];

function getAllText(msg) {
  let parts = [];
  if (msg.content) parts.push(msg.content);
  for (const e of msg.embeds || []) {
    if (e.title) parts.push(e.title);
    if (e.description) parts.push(e.description);
    for (const f of e.fields || []) {
      if (f.name) parts.push(f.name);
      if (f.value) parts.push(f.value);
    }
    if (e.footer?.text) parts.push(e.footer.text);
    if (e.author?.name) parts.push(e.author.name);
  }
  return parts.join("\n");
}

function iterComponents(msg) {
  const result = [];
  for (const row of msg.components || []) {
    for (const comp of row.components || []) {
      result.push(comp);
    }
  }
  return result;
}

function analyze(msg) {
  let riskScore = 0;
  let highConfidence = false;
  const keywords = [];
  const reasons = [];

  // --- KeywordRule ---
  const text = (msg.content || "").toLowerCase();
  for (const [pattern, score, high] of KEYWORDS) {
    if (text.includes(pattern.toLowerCase())) {
      riskScore += score;
      keywords.push(pattern);
      reasons.push(`keyword "${pattern}"`);
      if (high) highConfidence = true;
    }
  }

  // --- ButtonRule ---
  let score = 0;
  for (const comp of iterComponents(msg)) {
    if (comp.type === 2) {
      const label = (comp.label || "").toLowerCase();
      score += 2;
      if (label && BUTTON_KEYWORDS.some(kw => label.includes(kw))) {
        score += 3;
        reasons.push(`button "${comp.label}"`);
      } else {
        reasons.push(`unexpected button "${comp.label}"`);
      }
    }
  }
  riskScore += Math.min(score, 6);

  // --- SelectRule ---
  score = 0;
  for (const comp of iterComponents(msg)) {
    if (comp.type === 3) {
      score += 2;
      const combined = ((comp.placeholder || "") + " " +
        (comp.options || []).map(o => o.label || "").join(" ")).toLowerCase();
      if (SELECT_KEYWORDS.some(kw => combined.includes(kw))) {
        score += 3;
        reasons.push("verification select menu");
      } else {
        reasons.push("unexpected select menu");
      }
    }
  }
  riskScore += Math.min(score, 6);

  // --- PatternRule ---
  const interactive = [];
  for (const comp of iterComponents(msg)) {
    if (comp.type === 2 || comp.type === 3) interactive.push(comp);
  }
  if (interactive.length > 0) {
    riskScore += 2;
    reasons.push(`interactive component(s)`);
    const content = (msg.content || "").trim();
    const hasEmbeds = (msg.embeds || []).length > 0;
    if (content.length < 5 && !hasEmbeds) {
      riskScore += 1;
      reasons.push("bare interactive with minimal text");
    }
  }

  // --- ComboRule ---
  const allText = getAllText(msg).toLowerCase();
  const comps = [...iterComponents(msg)];
  const hasButton = comps.some(c => c.type === 2);
  const hasSelect = comps.some(c => c.type === 3);
  const hasInteractive = hasButton || hasSelect;
  const hasAttachment = (msg.attachments || []).length > 0;
  const hasHuman = allText.includes("human");
  const hasVerification = ["verify","verification","captcha","security check","human verification","prove","challenge"]
    .some(w => allText.includes(w));

  if (hasVerification && hasInteractive) { highConfidence = true; reasons.push("combo: verification+interactive"); }
  if (hasVerification && hasAttachment) { highConfidence = true; reasons.push("combo: verification+attachment"); }
  if (hasVerification && hasHuman) { highConfidence = true; reasons.push("combo: verification+human"); }
  if (hasButton && ["verify","captcha","prove","human"].some(w => allText.includes(w))) {
    riskScore += 3; reasons.push("button+verify keyword");
  }
  if (hasInteractive && ["click","tap","press"].some(w => allText.includes(w))) {
    riskScore += 3; reasons.push("click+interactive");
  }

  // --- NormalPatternRule (negative score) ---
  let normalScore = 0;
  for (const p of NORMAL_PATTERNS) {
    if (p.test(msg.content || "")) {
      normalScore -= 2;
      reasons.push("normal pattern match");
      break;
    }
  }
  const components = msg.components || [];
  const hasWrapper = components.some(c => c.type === 17);
  if (hasWrapper) {
    const allComps = components.flatMap(r => r.components || []);
    const hasTextDisplay = allComps.some(c => c.type === 10);
    const hasSeparator = allComps.some(c => c.type === 14);
    const hasInteractiveInner = allComps.some(c => c.type === 2 || c.type === 3);
    if (hasTextDisplay && hasSeparator && !hasInteractiveInner) {
      normalScore -= 3;
      reasons.push("Wrapper>Container>TextDisplay+Separator (normal battle)");
    }
  }

  riskScore += normalScore;

  let decision = "NORMAL";
  if (highConfidence) decision = "CAPTCHA";
  else if (riskScore >= 5) decision = "CAPTCHA";
  else if (riskScore > 0) decision = "SUSPICIOUS";

  return { riskScore, highConfidence, decision, keywords, reasons };
}

// --- Load live data ---
const lines = fs.readFileSync("lucy_collect.jsonl", "utf8").split("\n").filter(l => l.trim());
const liveMessages = lines.map(l => JSON.parse(l).msg);
console.log(`Loaded ${liveMessages.length} live Lucy messages\n`);

// --- Test live messages (should all be NORMAL) ---
let passCount = 0;
let failCount = 0;
const failures = [];
for (const msg of liveMessages) {
  const r = analyze(msg);
  if (r.decision === "NORMAL") {
    passCount++;
  } else {
    failCount++;
    failures.push({ id: msg.id, content: (msg.content || "").slice(0, 60), decision: r.decision, score: r.riskScore, reasons: r.reasons });
  }
}
console.log(`Live data results: ${passCount}/${liveMessages.length} NORMAL, ${failCount} non-NORMAL`);
if (failures.length > 0) {
  console.log("FAILURES:");
  for (const f of failures) {
    console.log(`  id=${f.id} decision=${f.decision} score=${f.score} reasons=${f.reasons.join("; ")}`);
    console.log(`    content: ${f.content}`);
  }
} else {
  console.log("✅ All live messages correctly classified as NORMAL\n");
}

// --- Test synthetic CAPTCHA messages ---
const captchaTests = [
  { name: "Text CAPTCHA", expected: "CAPTCHA", msg: { content: "Please verify that you are human.", embeds: [], components: [], attachments: [], author: {} } },
  { name: "Button CAPTCHA", expected: "CAPTCHA", msg: { content: "Verification required", embeds: [], components: [{ type: 1, components: [{ type: 2, label: "Verify" }] }], attachments: [], author: {} } },
  { name: "Select CAPTCHA", expected: "CAPTCHA", msg: { content: "Verification required", embeds: [], components: [{ type: 1, components: [{ type: 3, placeholder: "Select method", options: [{ label: "Verify" }] }] }], attachments: [], author: {} } },
  { name: "Embed CAPTCHA", expected: "CAPTCHA", msg: { content: "", embeds: [{ title: "Verification Required", description: "Please verify that you are human" }], components: [], attachments: [], author: {} } },
  { name: "Empty + Button", expected: "CAPTCHA", msg: { content: "", embeds: [], components: [{ type: 1, components: [{ type: 2, label: "Continue" }] }], attachments: [], author: {} } },
  { name: "Normal button (suspicious from Lucy)", expected: "SUSPICIOUS", msg: { content: "Pilih aksi", embeds: [], components: [{ type: 1, components: [{ type: 2, label: "Next" }] }], attachments: [], author: {} } },
  { name: "Normal attachment", expected: "NORMAL", msg: { content: "Pai hunt diperkuat", embeds: [], components: [], attachments: [{ filename: "loot.png", content_type: "image/png", size: 1234 }], author: {} } },
  { name: "Verify + attachment", expected: "CAPTCHA", msg: { content: "Verification required", embeds: [], components: [], attachments: [{ filename: "check.png", content_type: "image/png", size: 1234 }], author: {} } },
];

console.log("CAPTCHA detection tests:");
let captchaPass = 0;
let captchaFail = 0;
for (const t of captchaTests) {
  const r = analyze(t.msg);
  const expected = t.expected;
  const ok = r.decision === expected;
  if (ok) captchaPass++;
  else captchaFail++;
  console.log(`  ${ok ? "✅" : "❌"} ${t.name}: got=${r.decision} expected=${expected} score=${r.riskScore} reasons=[${r.reasons.join(", ")}]`);
}
console.log(`\nCAPTCHA tests: ${captchaPass}/${captchaTests.length} passed`);

// --- Summary ---
console.log("\n" + "=".repeat(50));
console.log(`TOTAL: ${passCount + captchaPass}/${liveMessages.length + captchaTests.length} correct classifications`);
if (failCount + captchaFail === 0) {
  console.log("🎉 ALL TESTS PASSED");
} else {
  console.log(`⚠️ ${failCount + captchaFail} failures`);
}
