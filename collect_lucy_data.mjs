/* Lucy data collector — mirrors rpg.py RPG_TASKS cooldowns.
 * Sends lh (0.1s) -> lb (0.1s) -> lucy (15s), repeat N cycles (default 20).
 * After each cycle fetches recent channel messages, saves NEW Lucy messages
 * (raw JSON) to lucy_collect.jsonl for captcha-handler refinement.
 * Also prints a lightweight keyword score per new Lucy message.
 * Usage: node collect_lucy_data.mjs [cycles]  (default 20)
 */
import fs from "fs";

function loadEnv(path = ".env") {
  const env = {};
  for (const line of fs.readFileSync(path, "utf8").split("\n")) {
    const t = line.trim();
    if (!t || t.startsWith("#") || !t.includes("=")) continue;
    const i = t.indexOf("=");
    env[t.slice(0, i).trim()] = t.slice(i + 1).trim();
  }
  return env;
}

const env = loadEnv();
const TOKEN = env.TOKEN,
  CHANNEL_ID = env.CHANNEL_ID,
  LUCY_BOT_ID = env.LUCY_BOT_ID;
if (!TOKEN || !CHANNEL_ID) {
  console.error("Missing TOKEN/CHANNEL_ID in .env");
  process.exit(1);
}

const CYCLES = parseInt(process.argv[2] || "20", 10);
const TASKS = [
  ["lh", 100],
  ["lb", 100],
  ["lucy", 15000],
];
const API = "https://discord.com/api/v9";
const HEADERS = {
  Authorization: TOKEN,
  "Content-Type": "application/json",
  "User-Agent": "Mozilla/5.0",
};
const OUT = "lucy_collect.jsonl";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const stamp = () => new Date().toTimeString().slice(0, 8);

// lightweight scorer (mirrors KEYWORDS in lucy_captcha_detector.py)
const KW = [
  "verify that you are human",
  "verify you are human",
  "prove you are human",
  "verify you're human",
  "prove you're human",
  "human verification",
  "are you human",
  "i am not a robot",
  "not a robot",
  "captcha",
  "verification required",
  "verification needed",
  "complete verification",
  "verify your identity",
  "security check",
  "security verification",
  "anti-bot",
  "anti bot",
  "bot detection",
  "suspicious activity",
  "unusual activity",
  "select all images",
  "click the squares",
  "click all squares",
];
function scoreMsg(m) {
  let text = m.content || "";
  for (const e of m.embeds || []) {
    text += "\n" + (e.title || "") + "\n" + (e.description || "");
    for (const f of e.fields || [])
      text += "\n" + (f.name || "") + "\n" + (f.value || "");
    if (e.footer?.text) text += "\n" + e.footer.text;
    if (e.author?.name) text += "\n" + e.author.name;
  }
  const low = text.toLowerCase();
  const hits = KW.filter((k) => low.includes(k));
  const nBtn = (m.components || [])
    .flatMap((r) => r.components || [])
    .filter((c) => c.type === 2 || c.type === 3).length;
  return { hits, nBtn, score: hits.length * 4 + Math.min(nBtn * 3, 6) };
}

async function send(content) {
  for (let attempt = 0; attempt < 3; attempt++) {
    const r = await fetch(`${API}/channels/${CHANNEL_ID}/messages`, {
      method: "POST",
      headers: HEADERS,
      body: JSON.stringify({ content, tts: false }),
    });
    if (r.status === 429) {
      const retry = ((await r.json()).retry_after || 2) * 1000;
      console.log(`[${stamp()}] 429 RATE LIMITED, wait ${retry}ms`);
      await sleep(retry + 500);
      continue;
    }
    if (r.status === 200) {
      console.log(`[${stamp()}] SENT: ${content}`);
      return true;
    }
    if (r.status === 401) {
      console.error(`[${stamp()}] 401 TOKEN INVALID — abort`);
      process.exit(1);
    }
    console.log(
      `[${stamp()}] SEND ${content} -> HTTP ${r.status} ${(await r.text()).slice(0, 120)}`,
    );
    return false;
  }
  return false;
}

const seen = new Set();
let newCount = 0;
// resume: skip messages already collected in a previous run
if (fs.existsSync(OUT)) {
  for (const line of fs.readFileSync(OUT, "utf8").split("\n")) {
    if (!line.trim()) continue;
    try {
      const o = JSON.parse(line);
      if (o.msg?.id) seen.add(o.msg.id);
    } catch {}
  }
  console.log(`[${stamp()}] Resuming, ${seen.size} messages already collected`);
}

async function fetchLucy(cycle, afterCmd) {
  const r = await fetch(`${API}/channels/${CHANNEL_ID}/messages?limit=30`, {
    headers: HEADERS,
  });
  if (r.status !== 200) {
    console.log(`[${stamp()}] FETCH ERROR HTTP ${r.status}`);
    return;
  }
  const msgs = await r.json();
  const lucy = msgs.filter(
    (m) => m.author?.id === LUCY_BOT_ID && !seen.has(m.id),
  );
  for (const m of lucy) {
    seen.add(m.id);
    newCount++;
    const s = scoreMsg(m);
    fs.appendFileSync(
      OUT,
      JSON.stringify({
        cycle,
        after_cmd: afterCmd,
        fetched_at: new Date().toISOString(),
        score: s,
        msg: m,
      }) + "\n",
    );
    const preview = (m.content || "").slice(0, 80).replace(/\n/g, " ");
    console.log(
      `[${stamp()}] LUCY #${newCount} c${cycle} score=${s.score} btn=${s.nBtn} hits=[${s.hits.join("|") || "-"}] embeds=${(m.embeds || []).length} :: ${preview || "(no content)"}`,
    );
  }
  if (!lucy.length) console.log(`[${stamp()}] c${cycle}: no new Lucy messages`);
}

(async () => {
  console.log(
    `[${stamp()}] START: ${CYCLES} cycles of lh/0.1s lb/0.1s lucy/15s -> ${OUT}`,
  );
  for (let c = 1; c <= CYCLES; c++) {
    console.log(`\n[${stamp()}] --- CYCLE ${c}/${CYCLES} ---`);
    for (const [cmd, delay] of TASKS) {
      await send(cmd);
      await sleep(delay);
    }
    await fetchLucy(c, "lucy");
  }
  console.log(
    `\n[${stamp()}] DONE: ${newCount} new Lucy messages this run, ${seen.size} total known. File: ${OUT}`,
  );
})();
