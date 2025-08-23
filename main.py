import asyncio
import os
import pandas as pd
from dotenv import load_dotenv
from pyrogram import Client, filters
from portalsmp import search as portals_search, update_auth as portals_update_auth

load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME")
SEARCH_LIMIT = int(os.getenv("SEARCH_LIMIT", "50"))

MODEL_TO_COLORS: dict[str, set[str]] = {}
mapping = pd.read_csv("model-backdrop-match.csv")
mapping['col'] = mapping['col'].apply(lambda x: str(x).lower().strip())
mapping['name'] = mapping['name'].apply(lambda x: str(x).lower().strip())
models = list(mapping['col'].unique())
for _, row in mapping.iterrows():
    MODEL_TO_COLORS.setdefault(row["col"], set()).add(row["name"])

app = Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH)


@app.on_message(filters.me & filters.command("search", prefixes=["/", "!", "."]))
async def cmd_search(_, msg):
    args = msg.command[1:]
    if not args:
        await msg.reply_text('Usage: /search "<model name>"')
        return

    model = " ".join(args).strip().lower()
    await msg.reply_text(f"Searching '{model}' (raw).")

    try:
        auth = await portals_update_auth(API_ID, API_HASH)
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
    await msg.reply_text("Начинаю бесконечный обход моделей...")
    while True:
        model = models[idx]
        try:
            auth = await portals_update_auth(API_ID, API_HASH)
            items = portals_search(sort="price_asc", limit=SEARCH_LIMIT, gift_name=model, authData=auth) or []

            allowed = MODEL_TO_COLORS.get(model, set())
            if allowed:
                items = [
                    it for it in items
                    if (lambda b: b in allowed)(
                        next((a.get("value").lower().strip() for a in it.get("attributes", []) if a.get("type") == "backdrop"), "")
                    )
                ]

            print(f"[LOOP:{model}] {len(items)} items")
            if items:
                await msg.reply_text(f"[{model}] нашёл {len(items)} штук, первая цена {items[0].get('price')} TON")

        except Exception as e:
            print(f"[LOOP:{model}] ERROR: {e}")

        idx = (idx + 1) % len(models)
        await asyncio.sleep(2)  


if __name__ == "__main__":
    app.run()