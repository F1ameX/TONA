import os
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, List
from datetime import datetime

from dotenv import load_dotenv
from pyrogram import Client, filters, idle
from pyrogram.types import Message

from portal import Portals

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger("tona")
load_dotenv()

class TONAApp:
    def __init__(self):
        self.api_id = int(os.getenv("API_ID"))
        self.api_hash = os.getenv("API_HASH")
        self.session_name = os.getenv("SESSION_NAME", "tona")

        self.csv_path = "model-backdrop-match.csv"
        self.search_limit = 100
        self.sleep_between_models = 0.95
        self.request_timeout = 3.0
        self.batch_size = 2
        
        self.client: Optional[Client] = None
        self.portals: Optional[Portals] = None
        
        self.loop_task: Optional[asyncio.Task] = None
        self.loop_running = False

        self.scan_task: Optional[asyncio.Task] = None
        self.scan_running = False

    async def initialize(self):
        self.client = Client(
            self.session_name, 
            api_id=self.api_id, 
            api_hash=self.api_hash
        )
        
        self.portals = Portals(
            api_id=self.api_id,
            api_hash=self.api_hash,
            csv_path=self.csv_path,
            request_timeout=self.request_timeout
        )
        
        self.register_handlers()
        
    def register_handlers(self):
        @self.client.on_message(filters.me & filters.command("start", prefixes=["/", "!", "."]))
        async def cmd_start(client, message: Message):
            await self.handle_start(message)
            
        @self.client.on_message(filters.me & filters.command("stop", prefixes=["/", "!", "."]))
        async def cmd_stop(client, message: Message):
            await self.handle_stop(message)

    async def handle_start(self, message: Message):
        if self.loop_task and not self.loop_task.done():
            await message.reply_text("Monitoring loop already running.")
            return

        self.loop_running = True

        async def on_items_found(items_batch: Dict[str, List[Dict]]):
            try:
                for model, items in items_batch.items():
                    for item in items:
                        name = item.get("name", "N/A")
                        price = float(item.get("price", 0))
                        floor_price = float(item.get("floor_price", 0))
                        
                        line = f"[PORTALS] {name} | {price} TON (floor {floor_price})"
                        logger.info(line)

                        if price > 0 and price < floor_price:
                            await self.buy_item(item, model, message)
                            
            except Exception as e:
                logger.error(f"Error in on_items_found callback: {e}")

        self.loop_task = asyncio.create_task(
            self.portals.optimized_loop(
                on_items=on_items_found,
                sleep_between=self.sleep_between_models,
                limit=self.search_limit,
                batch_size=self.batch_size,
                should_continue=lambda: self.loop_running
            )
        )
        
        await message.reply_text("Monitoring started.")
        logger.info("Monitoring loop started")

    async def handle_stop(self, message: Message):
        if not self.loop_running:
            await message.reply_text("Monitoring is not running.")
            return
            
        self.loop_running = False
        
        if self.loop_task and not self.loop_task.done():
            try:
                await asyncio.wait_for(self.loop_task, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("Loop task didn't finish in time, cancelling...")
                self.loop_task.cancel()
            except Exception as e:
                logger.error(f"Error waiting for loop task: {e}")
                
        await message.reply_text("Monitoring stopped.")
        logger.info("Monitoring loop stopped")

    async def buy_item(self, item: Dict, model: str, message: Message):
        try:
            item_id = item.get("id")
            price = item.get("price")
            
            logger.info(f"ATTEMPTING TO BUY: {model} item {item_id} for {price} TON (below floor)")
            await message.reply_text(f"ATTEMPTING TO BUY: {model} item {item_id} for {price} TON (below floor)")

            # success = await portals_buy_item(item_id, price)
            # if success:
            #     logger.info(f"Successfully bought {model} item {item_id}")
            # else:
            #     logger.warning(f"Failed to buy {model} item {item_id}")
                
        except Exception as e:
            logger.error(f"Error buying item {item.get('id')}: {e}")
    
    async def run(self):
        await self.initialize()
        
        try:
            async with self.client:
                logger.info("TONA application started")
                await idle()
        finally:
            self.loop_running = False
            if self.loop_task and not self.loop_task.done():
                self.loop_task.cancel()
                try:
                    await self.loop_task
                except asyncio.CancelledError:
                    pass
                logger.info("Application stopped, loop task cancelled")


if __name__ == "__main__":
    app = TONAApp()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Application error: {e}")