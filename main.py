# main.py
import os
import asyncio
from dotenv import load_dotenv
from pyrogram import Client, filters

from portal import PortalAutoBuyer, format_item as portal_fmt
from tonnel import TonnelAutoBuyer, format_item as tonnel_fmt

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME", "market_userbot")
TWOFA_PASSWORD = os.getenv("TWOFA_PASSWORD") or None

DRY_RUN = (os.getenv("DRY_RUN", "true").lower() == "true")
POLL_INTERVAL_SEC = float(os.getenv("POLL_INTERVAL_SEC", "1.5"))

# Portals
PORTALS_MAX_PRICE = float(os.getenv("PORTALS_MAX_PRICE", "0") or 0)
PORTALS_GIFT_NAME = (os.getenv("PORTALS_GIFT_NAME") or "").strip()
PORTALS_HARDCODED_AUTH = os.getenv("PORTALS_HARDCODED_AUTH") or None

# Tonnel
TONNEL_MAX_PRICE = float(os.getenv("TONNEL_MAX_PRICE", "0") or 0)
TONNEL_GIFT_NAME = (os.getenv("TONNEL_GIFT_NAME") or "").strip()
TONNEL_AUTH = os.getenv("TONNEL_AUTH")

app = Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH, password=TWOFA_PASSWORD)

portal_buyer = PortalAutoBuyer(
    api_id=API_ID,
    api_hash=API_HASH,
    poll_interval=POLL_INTERVAL_SEC,
    dry_run=DRY_RUN,
    hardcoded_auth=PORTALS_HARDCODED_AUTH
)

tonnel_buyer = TonnelAutoBuyer(
    auth=TONNEL_AUTH,
    poll_interval=POLL_INTERVAL_SEC,
    dry_run=DRY_RUN
)

both_task: asyncio.Task | None = None
both_stop = asyncio.Event()

async def send_me(text: str):
    await app.send_message("me", text)

# -------- ОБЪЕДИНЁННЫЕ КОМАНДЫ --------

@app.on_message(filters.me & filters.command("cheapest", prefixes=["/", "!", "."]))
async def cheapest_both(_, msg):
    """ /cheapest  [name]  — объединённый TOP-50 по цене (25+25) """
    name = " ".join(msg.command[1:]).strip()
    await msg.reply_text(f"Ищу самые дешёвые на обеих платформах… {f'({name})' if name else ''}")

    p_items, t_items = await asyncio.gather(
        portal_buyer.cheapest(name or PORTALS_GIFT_NAME, limit=25),
        tonnel_buyer.cheapest(name or TONNEL_GIFT_NAME, limit=25)
    )

    combined = []
    for it in p_items:
        try:
            combined.append(("PORTALS", float(it.get("price")), it))
        except Exception:
            pass
    for it in t_items:
        try:
            combined.append(("TONNEL", float(it.get("price")), it))
        except Exception:
            pass

    combined.sort(key=lambda x: x[1])
    if not combined:
        await msg.reply_text("Ничего не нашёл 🤷")
        return

    lines = []
    for i, (src, price, it) in enumerate(combined[:50], 1):
        if src == "PORTALS":
            lines.append(f"[PORTALS] {portal_fmt(it, i)}")
        else:
            lines.append(f"[TONNEL]  {tonnel_fmt(it, i)}")

    chunk, total, sz = [], [], 0
    for line in lines:
        if sz + len(line) + 1 > 3500:
            total.append("\n".join(chunk)); chunk, sz = [], 0
        chunk.append(line); sz += len(line) + 1
    if chunk: total.append("\n".join(chunk))
    for part in total:
        await msg.reply_text(part)

@app.on_message(filters.me & filters.command("autobuy", prefixes=["/", "!", "."]))
async def autobuy_both(_, msg):
    """
    /autobuy <max_price> [name]
    Один лимит и одно (опц.) имя — применяются к обеим платформам.
    Пример: /autobuy 31.5 "toy bear"
    """
    global both_task
    if both_task and not both_task.done():
        await msg.reply_text("Уже запущен. Останови /stop")
        return

    args = msg.command[1:]
    if args:
        try:
            max_price = float(args[0])
        except ValueError:
            await msg.reply_text("Первый аргумент — число (лимит цены). Пример: /autobuy 32.5")
            return
        name = " ".join(args[1:]).strip()
    else:
        max_price = max(PORTALS_MAX_PRICE or 0, TONNEL_MAX_PRICE or 0)
        name = (PORTALS_GIFT_NAME or TONNEL_GIFT_NAME or "").strip()
    if max_price <= 0:
        await msg.reply_text("Укажи лимит цены, например: /autobuy 32.5 \"toy bear\"")
        return

    both_stop.clear()

    async def run_portals():
        await portal_buyer.run(max_price, name, lambda text: send_me(f"[PORTALS] {text}"))
    async def run_tonnel():
        await tonnel_buyer.run(max_price, name, lambda text: send_me(f"[TONNEL]  {text}"))

    await send_me(f"🚀 Старт автобая на обеих платформах. "
                  f"max_price={max_price}, gift={name or 'ANY'}, DRY_RUN={DRY_RUN}")
    both_task = app.loop.create_task(asyncio.gather(run_portals(), run_tonnel()))
    await msg.reply_text("Запущено: /stop — чтобы остановить оба сразу")

@app.on_message(filters.me & filters.command("stop", prefixes=["/", "!", "."]))
async def stop_both(_, msg):
    portal_buyer.stop()
    tonnel_buyer.stop()
    await msg.reply_text("Останавливаю оба…")


@app.on_message(filters.me & filters.command("start", prefixes=["/", "!", "."]))
async def start_cmd(_, msg):
    await msg.reply_text(
        "Бот жив.\n"
        "Общее:\n"
        "  /cheapest [name] — объединённый топ-50 по цене\n"
        "  /autobuy <price> [name] — ЕДИНЫЙ автобай для обеих платформ\n"
        "  /stop — остановить обе\n\n"
        "Локальные (если надо по отдельности):\n"
        "  /portal_cheapest, /portal_autobuy, /portal_stop\n"
        "  /tonnel_cheapest, /tonnel_autobuy, /tonnel_stop\n"
        f"DRY_RUN={DRY_RUN}, POLL_INTERVAL={POLL_INTERVAL_SEC}s"
    )

if __name__ == "__main__":
    app.run()