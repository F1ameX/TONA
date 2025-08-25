import os
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, List, Callable

from dotenv import load_dotenv
from pyrogram import Client, filters, idle
from pyrogram.types import Message

from portal import Portals

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f"tona_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("tona")

load_dotenv()

class TONAApp:
    def __init__(self):
        self.api_id = int(os.getenv("API_ID"))
        self.api_hash = os.getenv("API_HASH")
        self.session_name = os.getenv("SESSION_NAME", "tona_arbitrage_bot")
        self.csv_path = os.getenv("CSV_PATH", "model-backdrop-match.csv")
        
        self.search_limit = int(os.getenv("SEARCH_LIMIT", "100"))
        self.sleep_between_models = float(os.getenv("SLEEP_BETWEEN_MODELS", "0.75"))
        self.request_timeout = float(os.getenv("REQUEST_TIMEOUT", "5.0"))
        self.batch_size = int(os.getenv("BATCH_SIZE", "2"))
        self.mrkt_check_interval = float(os.getenv("MRKT_CHECK_INTERVAL", "30.0"))
        
        self.client: Optional[Client] = None
        self.portals: Optional[Portals] = None
        self.mrkt_monitor: Optional[MRKT] = None
        self.portals_loop_task: Optional[asyncio.Task] = None
        self.mrkt_loop_task: Optional[asyncio.Task] = None
        self.loop_running = False

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
        
        # Инициализируем мониторинг MRKT
        self.mrkt_monitor = MRKT(self.client, self.portals)
        
        self.register_handlers()
        
    def register_handlers(self):
        
        @self.client.on_message(filters.me & filters.command("start", prefixes=["/", "!", "."]))
        async def cmd_start(client, message: Message):
            await self.handle_start(message)
            
        @self.client.on_message(filters.me & filters.command("stop", prefixes=["/", "!", "."]))
        async def cmd_stop(client, message: Message):
            await self.handle_stop(message)

    async def handle_start(self, message: Message):
        if (self.portals_loop_task and not self.portals_loop_task.done()) or \
           (self.mrkt_loop_task and not self.mrkt_loop_task.done()):
            await message.reply_text("Monitoring loop already running.")
            return

        self.loop_running = True

        # Callback для Portals
        async def on_portals_arbitrage(item: Dict, model: str):
            try:
                name = item.get("name", "N/A")
                price = float(item.get("price", 0))
                floor_price = float(item.get("floor_price", 0))
                
                line = f"[PORTALS] {model} → {name} | {price} TON (floor {floor_price})"
                
                logger.info(line)
                await self.client.send_message("me", line)

                if price > 0 and price < floor_price:
                    await self.buy_item(item, model, message)
                            
            except Exception as e:
                logger.error(f"Error in on_portals_arbitrage callback: {e}")

        # Callback для MRKT
        async def on_mrkt_arbitrage(gift: Dict):
            try:
                model = gift.get("model", "N/A")
                price = gift.get("price", 0)
                floor_price = gift.get("floor_price", 0)
                message_url = gift.get("message_url", "")
                
                line = f"[MRKT] {model} → {price} TON (floor {floor_price}) | {message_url}"
                
                logger.info(line)
                await self.client.send_message("me", line)

                if price > 0 and price < floor_price:
                    await self.buy_mrkt_gift(gift, message)
                            
            except Exception as e:
                logger.error(f"Error in on_mrkt_arbitrage callback: {e}")

        # Запускаем оба мониторинга
        self.portals_loop_task = asyncio.create_task(
            self._portals_loop(on_portals_arbitrage)
        )
        
        self.mrkt_loop_task = asyncio.create_task(
            self.mrkt_monitor.start_monitoring(
                on_arbitrage=on_mrkt_arbitrage,
                interval=self.mrkt_check_interval,
                should_continue=lambda: self.loop_running
            )
        )
        
        await message.reply_text("Dual monitoring started. Results will be sent to Saved Messages.")
        logger.info("Dual monitoring loop started")

    async def _portals_loop(self, on_arbitrage: Callable):
        """Основной цикл мониторинга Portals"""
        async def on_items_found(items_batch: Dict[str, List[Dict]]):
            try:
                for model, items in items_batch.items():
                    for item in items:
                        await on_arbitrage(item, model)
            except Exception as e:
                logger.error(f"Error in on_items_found callback: {e}")

        await self.portals.optimized_loop(
            on_items=on_items_found,
            sleep_between=self.sleep_between_models,
            limit=self.search_limit,
            batch_size=self.batch_size,
            should_continue=lambda: self.loop_running
        )

    async def handle_stop(self, message: Message):
        if not self.loop_running:
            await message.reply_text("Monitoring is not running.")
            return
            
        self.loop_running = False
        
        # Останавливаем оба цикла
        tasks = []
        if self.portals_loop_task and not self.portals_loop_task.done():
            tasks.append(self.portals_loop_task)
        if self.mrkt_loop_task and not self.mrkt_loop_task.done():
            tasks.append(self.mrkt_loop_task)
        
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=15.0)
            except asyncio.TimeoutError:
                logger.warning("Loop tasks didn't finish in time, cancelling...")
                for task in tasks:
                    task.cancel()
            except Exception as e:
                logger.error(f"Error waiting for loop tasks: {e}")
                
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

    async def buy_mrkt_gift(self, gift: Dict, message: Message):
        try:
            gift_id = gift.get("id")
            price = gift.get("price")
            model = gift.get("model")
            channel = gift.get("channel")
            
            logger.info(f"ATTEMPTING TO BUY: {model} gift in @{channel} for {price} TON (below floor)")
            await message.reply_text(f"ATTEMPTING TO BUY: {model} gift in @{channel} for {price} TON (below floor)")

            # Здесь можно добавить логику покупки через Telegram
            # Например, отправить сообщение продавцу
            # await self.client.send_message(channel, f"Хочу купить {model} за {price} TON")
                
        except Exception as e:
            logger.error(f"Error buying MRKT gift: {e}")

    async def run(self):
        await self.initialize()
        
        try:
            async with self.client:
                logger.info("TONA application started")
                await idle()
        finally:
            self.loop_running = False
            tasks = []
            if self.portals_loop_task and not self.portals_loop_task.done():
                tasks.append(self.portals_loop_task)
            if self.mrkt_loop_task and not self.mrkt_loop_task.done():
                tasks.append(self.mrkt_loop_task)
            
            for task in tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
            logger.info("Application stopped, all tasks cancelled")

if __name__ == "__main__":
    app = TONAApp()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Application error: {e}")