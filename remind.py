"""Discord-напоминалки о событиях Rise of Kingdoms через вебхук.

Запускается по расписанию (GitHub Actions каждые 10 минут).
Сам вычисляет время событий по якорю и интервалу, поэтому список не заканчивается.
Отправленные напоминания пишет в sent.json, чтобы не было дублей.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import requests

# ── НАСТРОЙКИ ────────────────────────────────────────────────────────────────
# anchor — любое известное время события в UTC, every_h — интервал в часах.
EVENTS = [
    {"name": "Ancient Ruins", "emoji": "🏛️", "anchor": "2026-10-27 15:05", "every_h": 40},
    {"name": "Altar of Darkness", "emoji": "🔥", "anchor": "2026-11-11 15:05", "every_h": 86},
]

# За сколько минут до начала напоминать (0 = в момент начала).
LEADS_MIN = [240, 120, 60, 15]

# Кого пинговать: "" — никого, "@here" или "@everyone".
MENTION = "@everyone"
# На каких напоминаниях пинговать (минуты из LEADS_MIN). Например [15] — только за 15 минут.
MENTION_AT = [240, 120, 60, 15]

# Текст сообщения. <t:...:R> и <t:...:t> Discord покажет каждому в его часовом поясе.
TEMPLATE = "{emoji} **{name}** starts <t:{ts}:R> (at <t:{ts}:t>) {mention}"
# ─────────────────────────────────────────────────────────────────────────────

SENT_FILE = "sent.json"


def parse_utc(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def occurrences(ev, start, end):
    """Все начала события в интервале [start, end]."""
    anchor = parse_utc(ev["anchor"])
    step = timedelta(hours=ev["every_h"])
    n = max(0, int((start - anchor) / step))
    t = anchor + n * step
    while t <= end:
        if t >= start:
            yield t
        t += step


def load_sent():
    try:
        with open(SENT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_sent(sent, now):
    # Чистим записи старше недели, чтобы файл не рос.
    cutoff = (now - timedelta(days=7)).isoformat()
    sent = {k: v for k, v in sent.items() if v >= cutoff}
    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(sent, f, indent=1, ensure_ascii=False, sort_keys=True)


def send(text):
    if os.environ.get("DRY_RUN"):
        print("[DRY RUN]", text)
        return
    url = os.environ["DISCORD_WEBHOOK"]
    r = requests.post(url, json={"content": text, "username": "RoK Reminder"}, timeout=20)
    r.raise_for_status()


def main():
    now = datetime.now(timezone.utc)
    if os.environ.get("NOW"):  # для теста: NOW="2026-10-29 06:10"
        now = parse_utc(os.environ["NOW"])

    if os.environ.get("TEST") == "true":
        # Тестовое сообщение: показывает ближайшее начало каждого события.
        lines = ["✅ Test: reminders are working. Next events:"]
        for ev in EVENTS:
            horizon = max(now, parse_utc(ev["anchor"])) + timedelta(hours=ev["every_h"])
            t = next(occurrences(ev, now, horizon))
            ts = int(t.timestamp())
            lines.append(f"{ev['emoji']} **{ev['name']}** — <t:{ts}:F> (<t:{ts}:R>)")
        send("\n".join(lines))
        return

    sent = load_sent()
    max_lead = timedelta(minutes=max(LEADS_MIN))

    for ev in EVENTS:
        # Только события, которые ещё не начались (или начинаются прямо сейчас).
        for t in occurrences(ev, now - timedelta(minutes=5), now + max_lead):
            # Какие напоминания по этому событию уже "наступили"?
            due = [lead for lead in LEADS_MIN if t - timedelta(minutes=lead) <= now]
            if not due:
                continue
            keys = {lead: f"{ev['name']}|{t.isoformat()}|{lead}" for lead in due}
            pending = [lead for lead in due if keys[lead] not in sent]
            if not pending:
                continue
            # Если запуск опоздал и созрело сразу несколько — шлём одно, самое свежее.
            ts = int(t.timestamp())
            mention = MENTION if min(pending) in MENTION_AT else ""
            text = TEMPLATE.format(emoji=ev["emoji"], name=ev["name"], ts=ts,
                                   mention=mention).strip()
            send(text)
            for lead in due:
                sent[keys[lead]] = now.isoformat()

    save_sent(sent, now)


if __name__ == "__main__":
    main()
