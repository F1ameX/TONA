import asyncio
import os
import time
import pandas as pd
from dotenv import load_dotenv
from pyrogram import Client, filters
from portalsmp import search as portals_search, update_auth as portals_update_auth

load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME")

PORTALS_AUTH_CACHE: dict[str, str] = {}
PORTALS_AUTH_TS: float | None = None
PORTALS_AUTH_TTL = 30 * 60

async def get_portals_auth() -> str:
    """Возвращает auth для Portals, с кэшем (чтобы не дергать Telegram каждый раз)."""
    global PORTALS_AUTH_TS
    hardcoded = os.getenv("PORTALS_HARDCODED_AUTH")
    if hardcoded:
        return hardcoded

    now = time.time()
    if PORTALS_AUTH_TS and (now - PORTALS_AUTH_TS) < PORTALS_AUTH_TTL and "token" in PORTALS_AUTH_CACHE:
        return PORTALS_AUTH_CACHE["token"]

    token = await portals_update_auth(API_ID, API_HASH)
    PORTALS_AUTH_CACHE["token"] = token
    PORTALS_AUTH_TS = now
    return token


MODEL_TO_COLORS: dict[str, set[str]] = {}
mapping = pd.read_csv("model-backdrop-match.csv")
mapping['col'] = mapping['col'].apply(lambda x: str(x).lower().strip())
mapping['name'] = mapping['name'].apply(lambda x: str(x).lower().strip())
models = list(mapping['col'].unique())
for _, row in mapping.iterrows():
    MODEL_TO_COLORS.setdefault(row["col"], set()).add(row["name"])

app = Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH, workdir=".", plugins=None, in_memory=True)


@app.on_message(filters.me & filters.command("search", prefixes=["/", "!", "."]))
async def cmd_search(_, msg):
    args = msg.command[1:]
    if not args:
        await msg.reply_text('Usage: /search "<model name>"')
        return

    model = " ".join(args).strip().lower()
    await msg.reply_text(f"Searching '{model}' (raw).")

    try:
        auth = await get_portals_auth()
        items = portals_search(sort="price_asc", gift_name=model, authData=auth) or []
        for item in items:
            attributes = item.get("attributes", [])
            for attr in attributes:
                if attr.get("type") == "backdrop":  
                    backdrop_value = attr.get("value").lower().strip()
                    if backdrop_value in MODEL_TO_COLORS.get(model, set()):
                        await msg.reply_text(f"[PORTALS] Name:{item['name']}, Price:{item['price']}, Floor:{item['floor_price']}")
                        print(item['name'])

    except Exception as e:
        await msg.reply_text(f"[PORTALS ERROR] {e}")


@app.on_message(filters.me & filters.command("start", prefixes=["/", "!", "."]))
async def cmd_start(_, msg):
    idx = 0
    await msg.reply_text("Pinging models")
    while True:
        model = models[idx]
        try:
            auth = await get_portals_auth()
            items = portals_search(sort="price_asc", gift_name=model, authData=auth) or []

            for item in items:
                attributes = item.get("attributes", [])
                for attr in attributes:
                    if attr.get("type") == "backdrop":  
                        backdrop_value = attr.get("value").lower().strip()
                        if backdrop_value in MODEL_TO_COLORS.get(model, set()):
                            print(f"[PORTALS] Name:{item['name']}, Price:{item['price']}, Floor:{item['floor_price']}")

        except Exception as e:
            await msg.reply_text(f"[PORTALS ERROR] {e}")

        idx = (idx + 1) % len(models)
        await asyncio.sleep(0.3)

if __name__ == "__main__":
    app.run()