import asyncio
from typing import Optional, Callable, Awaitable, Set

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from tonnelmp import getGifts, buyGift


def format_item(g: dict, i: int | None = None) -> str:
    head = f"{i:02d}. " if i is not None else ""
    parts = [p for p in (g.get("model"), g.get("symbol"), g.get("backdrop")) if p]
    tail = f" [{' | '.join(parts)}]" if parts else ""
    return f"{head}{g.get('name','?')} #{g.get('gift_num')} — {g.get('price')} TON{tail}"


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _buy_once(gift_id: int, price: float, auth: str):
    return buyGift(gift_id=gift_id, price=price, authData=auth)


class TonnelAutoBuyer:
    """
    Обёртка под Tonnel: поиск самых дешёвых и автопокупка.
    send: Callable[[str], Awaitable[None]] — корутина отправки сообщений.
    """

    def __init__(self, auth: str, poll_interval: float, dry_run: bool):
        self.auth = auth  
        self.poll_interval = poll_interval
        self.dry_run = dry_run

        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    async def cheapest(self, gift_name: Optional[str], limit: int) -> list[dict]:
        return getGifts(gift_name=gift_name or None, sort="price_asc", limit=limit, authData=self.auth) or []

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self, max_price: float, gift_name: str, send: Callable[[str], Awaitable[None]]) -> None:
        """
        Фоновый цикл: мониторит рынок и покупает (если DRY_RUN=False).
        """
        self._stop_event.clear()
        await send(
            f"Tonnel автобайер запущен. max_price={max_price}, gift={gift_name or 'ANY'}, dry_run={self.dry_run}"
        )

        seen: Set[int] = set()

        while not self._stop_event.is_set():
            try:
                items = await self.cheapest(gift_name, limit=50)
                deals = [
                    g for g in items
                    if isinstance(g.get("price"), (int, float)) and float(g["price"]) <= max_price
                ]

                for g in deals:
                    gid = int(g["gift_id"])
                    if gid in seen:
                        continue
                    seen.add(gid)

                    await send(f"🎯 Найден лот: {format_item(g)}")

                    if self.dry_run:
                        continue

                    try:
                        res = await asyncio.to_thread(_buy_once, gid, float(g["price"]), self.auth)
                        await send(f"Покупка отправлена: {format_item(g)}\nОтвет: {res}")
                    except Exception as e:
                        await send(f"Ошибка покупки: {e}")

                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                await send(f"Loop error (Tonnel): {e}")
                await asyncio.sleep(2.0)

        await send("Tonnel автобайер остановлен.")