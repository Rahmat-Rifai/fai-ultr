# PRD — Lucy CAPTCHA Detection & Automatic Bot Stop

## 1. Tujuan

Buat sistem pada Discord bot yang dapat mendeteksi ketika bot **Lucy** mengirim pesan yang kemungkinan merupakan CAPTCHA / anti-bot challenge, kemudian **menghentikan seluruh aktivitas otomatis bot** agar bot tidak melanjutkan command atau interaksi yang berpotensi memperburuk kondisi.

Bot saat ini hanya menjalankan command terhadap Lucy:
- `lh`
- `lb`
- `lucy`

Format balasan Lucy belum diketahui untuk CAPTCHA. Karena itu sistem harus dirancang agar dapat **mendeteksi secara generik, mencatat pesan mencurigakan, dan mudah diperbarui setelah contoh CAPTCHA nyata ditemukan**.

> Catatan: jangan mencoba menyelesaikan, melewati, atau mengotomatisasi CAPTCHA. Sistem hanya bertugas mendeteksi dan menghentikan bot.

---

## 2. Scope

### In scope

1. Memantau pesan dari Lucy.
2. Mengidentifikasi pesan yang berpotensi CAPTCHA.
3. Mendukung pesan:
   - plain text
   - embed
   - button
   - select menu / interactive components
   - attachment
   - link
4. Memberikan confidence/risk score.
5. Menghentikan seluruh task otomatis ketika threshold tercapai.
6. Menyimpan detail pesan yang menyebabkan trigger ke log.
7. Menyediakan mode monitoring/debug agar format CAPTCHA yang belum diketahui dapat dianalisis.
8. Memisahkan detector dari logic command agar mudah dirawat.

### Out of scope

- Menyelesaikan CAPTCHA.
- Mengklik CAPTCHA.
- OCR untuk membaca CAPTCHA lalu menjawabnya.
- Mengakali anti-bot.
- Bypass rate limit atau sistem keamanan Lucy.

---

# 3. Arsitektur yang diinginkan

Pisahkan sistem menjadi beberapa komponen:

```text
Discord Message
      │
      ▼
Lucy Message Filter
      │
      ▼
CAPTCHA Detector
      │
      ├── Text Analyzer
      ├── Embed Analyzer
      ├── Component Analyzer
      ├── Attachment Analyzer
      └── Message Pattern Analyzer
      │
      ▼
Risk / Confidence Score
      │
      ├── NORMAL
      │
      └── SUSPICIOUS / CAPTCHA
                    │
                    ▼
              Safety Stop
                    │
                    ▼
              Logger / Audit
```

Detector jangan dicampur langsung dengan kode command `lh`, `lb`, dan `lucy`.

---

# 4. Lucy Identification

Gunakan **Lucy bot user ID** sebagai identifikasi utama.

Jangan hanya mengandalkan:

```python
message.author.name == "Lucy"
```

karena username/display name dapat berubah.

Gunakan konfigurasi:

```python
LUCY_BOT_ID = ...
```

Jika ID belum diketahui, implementasikan konfigurasi yang mudah diisi.

Optional fallback:
- bot flag (`message.author.bot`)
- username/display name `Lucy`

Namun ID harus menjadi metode utama.

---

# 5. Command yang digunakan

Bot hanya melakukan command berikut terhadap Lucy:

```text
lh
lb
lucy
```

Detector tidak perlu menganggap semua pesan dari Lucy sebagai CAPTCHA.

Pesan normal seperti:

```text
Pai, hunt diperkuat oleh ...
Kamu menemukan: ...
mendapatkan ...xp!

Pai bertarung!
L.19 ...
L.18 ...
Tim Musuh
...
Kamu menang dalam ... giliran!
```

harus dianggap normal selama tidak memenuhi rule CAPTCHA.

---

# 6. Detection Strategy

Gunakan kombinasi beberapa indikator, bukan satu keyword saja.

## 6.1 Text keywords

Detector dapat memeriksa kata/frasa seperti:

```text
captcha
verification
verify
verify that you are human
are you human
human verification
robot
challenge
security check
anti bot
anti-bot
```

Gunakan case-insensitive matching.

Jangan membuat kata `verify` sendirian langsung menyebabkan stop jika berpotensi menghasilkan false positive.

---

## 6.2 Embed analysis

Periksa:

- embed title
- embed description
- embed fields
- footer
- author name
- URL

Keyword CAPTCHA pada embed harus meningkatkan risk score.

Contoh:

```text
title: Verification Required
description: Please verify that you are human
```

harus mendapat confidence tinggi.

---

## 6.3 Interactive components

Periksa:

- Button
- Select menu
- Interactive component lain yang tersedia melalui library Discord yang digunakan.

Jangan otomatis menganggap semua component sebagai CAPTCHA.

Component hanya menjadi indikator tambahan kecuali:
- label/text button mengandung indikasi verification/CAPTCHA, atau
- component muncul bersama indikator mencurigakan lainnya.

Contoh:

```text
[Verify]
```

→ risk meningkat.

---

## 6.4 Attachment

Periksa apakah pesan Lucy memiliki:

- image
- file
- attachment yang tidak biasa

Attachment saja tidak cukup untuk trigger CAPTCHA karena bisa saja merupakan bagian dari pesan normal.

Attachment + text seperti `verify` / `captcha` → confidence tinggi.

---

## 6.5 URL

Periksa URL dalam:

- message content
- embed URL
- button URL jika tersedia

URL yang berkaitan dengan verification/challenge dapat meningkatkan risk score.

Jangan melakukan request/fetch otomatis ke URL tersebut.

---

# 7. Risk Scoring

Gunakan scoring agar detector tidak terlalu agresif.

Contoh baseline:

| Indikator | Score |
|---|---:|
| Keyword `captcha` | +5 |
| Frasa `verify that you are human` | +5 |
| `human verification` | +5 |
| `verification required` | +4 |
| `challenge` dalam konteks verification | +3 |
| Button `Verify` | +3 |
| Select menu terkait verification | +3 |
| Verification URL | +3 |
| Attachment + indikator verification | +2 |
| Message format sangat berbeda dari response normal | +1 |
| Lucy bot ID cocok | filter wajib, bukan score |

Default:

```text
score >= 5
    → CAPTCHA/SUSPICIOUS
    → STOP BOT
```

Score harus configurable melalui config/env.

---

# 8. High Confidence Rule

Buat rule khusus untuk kombinasi kuat.

Contoh:

```text
"verify that you are human"
→ immediate stop
```

atau:

```text
captcha keyword + interactive button
→ immediate stop
```

atau:

```text
verification keyword + suspicious attachment
→ immediate stop
```

Tujuannya menghindari false negative.

---

# 9. Monitoring Mode

Karena format CAPTCHA Lucy belum diketahui, implementasikan mode:

```text
CAPTCHA_MONITOR_MODE=true
```

Dalam mode ini, detector tetap menganalisis pesan tetapi dapat dikonfigurasi agar:

```text
NORMAL
    → tidak melakukan apa-apa

SUSPICIOUS
    → log detail

HIGH CONFIDENCE CAPTCHA
    → STOP BOT
```

Alternatif mode:

```text
STRICT
```

Semua high-confidence detection langsung menghentikan bot.

---

# 10. Logging

Ketika pesan Lucy dianggap mencurigakan, simpan informasi:

```text
timestamp
guild_id
channel_id
message_id
author_id
author_name
message_content
embed_count
embed_data
component_count
component_data
attachment_count
attachment_metadata
detected_keywords
risk_score
trigger_reasons
action_taken
```

Jangan menyimpan token Discord, password, credential, atau secret lain.

---

# 11. Contoh log

```text
[CAPTCHA DETECTOR]
Time       : 2026-09-06 00:34:00
Author     : Lucy
Author ID  : 123456789
Channel    : lucy-spam1
Message ID : 987654321

Risk Score : 8

Reasons:
- "verification" keyword detected
- Button "Verify" detected

Action:
STOP BOT
```

Jika mode monitoring tidak melakukan stop:

```text
Action:
FLAGGED ONLY
```

---

# 12. Safety Stop

Buat satu fungsi pusat:

```python
async def emergency_stop(reason: str):
    ...
```

Fungsi ini harus menghentikan seluruh aktivitas otomatis, termasuk:

- command loop
- spam loop
- scheduled tasks
- asyncio tasks yang dibuat bot
- retry loop
- queue worker yang mengirim command
- automation loop lainnya

Jangan hanya menghentikan satu command.

Gunakan state global/application state:

```python
bot_running = True
captcha_detected = False
```

Ketika CAPTCHA terdeteksi:

```python
captcha_detected = True
bot_running = False
```

Semua loop harus mengecek state tersebut sebelum mengirim command baru.

---

# 13. Idempotent Stop

`emergency_stop()` harus aman jika dipanggil berkali-kali.

Contoh:

```text
CAPTCHA detected
→ emergency_stop()

Pesan CAPTCHA kedua
→ emergency_stop()
```

Jangan menghasilkan banyak cleanup/error.

Gunakan guard:

```python
if already_stopped:
    return
```

---

# 14. Behavior Setelah Stop

Setelah CAPTCHA terdeteksi:

1. Jangan kirim command baru ke Lucy.
2. Batalkan task otomatis.
3. Hentikan queue pengiriman.
4. Simpan log.
5. Tampilkan warning di console.
6. Pertahankan bot Discord tetap online jika memungkinkan.
7. Jangan mencoba berinteraksi dengan CAPTCHA.
8. Tunggu intervensi/manual reset.

Contoh:

```text
==================================================
⚠️ CAPTCHA / ANTI-BOT DETECTED
Lucy sent a suspicious message.

Risk score: 8
Reason:
- verification keyword
- Verify button

🛑 AUTOMATION STOPPED
==================================================
```

Bot Discord tidak harus disconnect; yang dihentikan adalah automation-nya.

---

# 15. Reset

Sediakan mekanisme reset manual.

Contoh command lokal:

```text
!captcha_reset
```

atau fungsi:

```python
reset_automation()
```

Reset tidak boleh otomatis dilakukan.

Tujuannya mencegah bot kembali berjalan terus-menerus setelah CAPTCHA.

---

# 16. Normal Message Compatibility

Detector harus memperhitungkan bahwa response Lucy dapat berupa embed seperti screenshot/contoh berikut:

```text
Pai bertarung!

L.19 ...
652 HP 286 WP
L.18 ...
536 HP 18 WP
L.14 ...
638 HP 118 WP

Tim Musuh
L.11 ...
L.11 ...
L.11 ...

Kamu menang dalam 4 giliran!
Tim kamu mendapat 200 xp!
```

Pesan seperti ini tidak boleh dianggap CAPTCHA hanya karena:
- menggunakan embed
- memiliki emoji
- memiliki banyak text
- memiliki image/icon
- memiliki field
- berasal dari Lucy

Detector harus fokus pada indikator verification/challenge.

---

# 17. Unknown CAPTCHA Format

Karena format CAPTCHA belum diketahui, implementasikan detector dengan extensible rules.

Contoh interface:

```python
class DetectionRule:
    name: str

    def evaluate(self, message) -> DetectionResult:
        ...
```

Contoh rules:

```text
KeywordRule
EmbedRule
ButtonRule
SelectRule
AttachmentRule
UrlRule
PatternRule
```

Kemudian:

```python
detector = CaptchaDetector([
    KeywordRule(),
    EmbedRule(),
    ButtonRule(),
    SelectRule(),
    AttachmentRule(),
    UrlRule(),
])
```

Dengan desain ini rule baru dapat ditambahkan tanpa mengubah command handler.

---

# 18. Configuration

Semua parameter penting harus configurable.

Contoh:

```env
LUCY_BOT_ID=123456789
CAPTCHA_DETECTION_ENABLED=true
CAPTCHA_STOP_THRESHOLD=5
CAPTCHA_MONITOR_MODE=true
CAPTCHA_LOG_ENABLED=true
```

Jangan hardcode threshold jika tidak diperlukan.

---

# 19. False Positive Prevention

Prioritas:

```text
False Positive > False Negative
```

untuk aktivitas normal, tetapi CAPTCHA ber-confidence tinggi harus selalu menyebabkan stop.

Jangan membuat rule:

```python
if "verify" in text:
    stop()
```

karena terlalu agresif.

Lebih baik:

```text
verify
+ button
= high confidence

verification
+ human
= high confidence

captcha
= very high confidence
```

---

# 20. Testing

Buat unit test untuk minimal:

### Test 1 — Normal Lucy hunt

Expected:

```text
NORMAL
Bot continues
```

### Test 2 — Normal battle embed

Expected:

```text
NORMAL
Bot continues
```

### Test 3 — Text CAPTCHA

Input:

```text
Please verify that you are human.
```

Expected:

```text
CAPTCHA
Bot stops
```

### Test 4 — Button CAPTCHA

Input:

```text
Verification required
[Verify]
```

Expected:

```text
CAPTCHA
Bot stops
```

### Test 5 — Normal button

Jika Lucy mempunyai button normal yang bukan verification:

Expected:

```text
NOT CAPTCHA
```

### Test 6 — Attachment normal

Expected:

```text
NOT CAPTCHA
```

### Test 7 — Verification + attachment

Expected:

```text
CAPTCHA
Bot stops
```

### Test 8 — Duplicate CAPTCHA messages

Expected:

```text
Only one emergency-stop sequence
No duplicate cleanup errors
```

---

# 21. Runtime Monitoring

Tambahkan log sederhana:

```text
[LUCY] Normal response
[LUCY] Normal response
[LUCY] Suspicious response — score 3
[LUCY] CAPTCHA detected — score 8
[SYSTEM] Automation stopped
```

Jangan spam log terlalu banyak untuk pesan normal.

---

# 22. Implementation Requirements

Sebelum mengubah code existing:

1. Inspect struktur project.
2. Identifikasi library Discord yang digunakan.
3. Identifikasi entry point bot.
4. Identifikasi command sender untuk:
   - `lh`
   - `lb`
   - `lucy`
5. Identifikasi semua background task/loop.
6. Identifikasi queue/retry mechanism.
7. Implementasikan detector sebagai module terpisah.
8. Integrasikan detector ke global message listener.
9. Integrasikan emergency stop ke seluruh automation loop.
10. Tambahkan unit tests.
11. Jangan merusak command existing.

Jika project sudah memiliki architecture/cog/service tertentu, ikuti architecture tersebut daripada membuat duplicate system.

---

# 23. Acceptance Criteria

Implementasi dianggap selesai jika:

- [ ] Hanya pesan dari Lucy yang dianalisis sebagai target utama.
- [ ] `lh`, `lb`, dan `lucy` tetap berjalan normal.
- [ ] Normal response Lucy tidak menyebabkan stop.
- [ ] CAPTCHA dengan keyword kuat terdeteksi.
- [ ] CAPTCHA berbasis button/verification dapat terdeteksi.
- [ ] Embed dianalisis.
- [ ] Attachment dapat menjadi indikator tambahan.
- [ ] Risk score configurable.
- [ ] Semua automation task berhenti ketika CAPTCHA high-confidence terdeteksi.
- [ ] Tidak ada command baru yang dikirim setelah emergency stop.
- [ ] Stop bersifat idempotent.
- [ ] Detail pesan pemicu tersimpan di log.
- [ ] Tidak ada CAPTCHA solving/bypass.
- [ ] Ada unit test untuk normal dan suspicious message.
- [ ] Detector mudah diperluas setelah format CAPTCHA nyata diketahui.

---

# 24. Instruksi untuk AI Agent

Kerjakan PRD ini pada existing project.

**Jangan langsung menebak format CAPTCHA Lucy.** Implementasikan detector generik + logging terlebih dahulu.

Prioritas pengerjaan:

```text
1. Inspect existing code
2. Identify Lucy message handling
3. Identify automation loops
4. Implement CaptchaDetector
5. Implement risk scoring
6. Implement emergency_stop
7. Integrate with all automation loops
8. Implement detailed logging
9. Add tests
10. Verify normal lh/lb/lucy flow remains unchanged
```

Jika menemukan format CAPTCHA yang tidak tercakup oleh rule awal, buat rule yang modular agar dapat ditambahkan kemudian.

**Jangan pernah mencoba menyelesaikan atau melewati CAPTCHA.**
