import asyncio
import inspect
from typing import Optional, List, Callable, Awaitable, Set

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from portalsmp import search, update_auth, buy as portals_buy


def _pick_attr(attrs: List[dict], t: str) -> str:
    return next((a.get("value") for a in (attrs or []) if a.get("type") == t), "")


def format_item(it: dict, i: int | None = None) -> str:
    head = f"{i:02d}. " if i is not None else ""
    attrs = it.get("attributes", [])
    model = _pick_attr(attrs, "model")
    symbol = _pick_attr(attrs, "symbol")
    backdrop = _pick_attr(attrs, "backdrop")
    parts = [p for p in (model, symbol, backdrop) if p]
    tail = f" [{' | '.join(parts)}]" if parts else ""
    return f"{head}{it.get('name')} #{it.get('tg_id')} — {it.get('price')} TON{tail}"


def _buy_signature_has_owner_id() -> bool:
    try:
        return "owner_id" in inspect.signature(portals_buy).parameters
    except Exception:
        return False


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _buy_once(nft_id: str, price: float, auth: str, owner_id: Optional[int] = None):
    if _buy_signature_has_owner_id() and owner_id is not None:
        return portals_buy(nft_id=nft_id, owner_id=owner_id, price=price, authData=auth)
    return portals_buy(nft_id=nft_id, price=price, authData=auth)


class PortalAutoBuyer:
    """
    Обёртка под Portals: поиск самых дешёвых и автопокупка.
    send: Callable[[str], Awaitable[None]] — корутина отправки сообщений.
    """

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        poll_interval: float,
        dry_run: bool,
        hardcoded_auth: Optional[str] = None,
    ):
        self.api_id = api_id
        self.api_hash = api_hash
        self.poll_interval = poll_interval
        self.dry_run = dry_run
        self.hardcoded_auth = hardcoded_auth

        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    async def _get_auth(self) -> str:
        if self.hardcoded_auth:
            return self.hardcoded_auth
        return await update_auth(self.api_id, self.api_hash)

    async def cheapest(self, gift_name: Optional[str], limit: int, auth: Optional[str] = None) -> list[dict]:
        token = auth or await self._get_auth()
        return search(sort="price_asc", limit=limit, gift_name=gift_name or "", authData=token) or []

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self, max_price: float, gift_name: str, send: Callable[[str], Awaitable[None]]) -> None:
        """
        Фоновый цикл: мониторит рынок и покупает (если DRY_RUN=False).
        """
        self._stop_event.clear()
        auth = await self._get_auth()
        await send(
            f"Portals автобайер запущен. max_price={max_price}, gift={gift_name or 'ANY'}, dry_run={self.dry_run}"
        )

        seen: Set[str] = set()

        while not self._stop_event.is_set():
            try:
                items = await self.cheapest(gift_name, limit=50, auth=auth)

                deals: list[dict] = []
                for it in items:
                    try:
                        if float(it.get("price", 1e18)) <= max_price:
                            deals.append(it)
                    except Exception:
                        pass

                for it in deals:
                    nid = it.get("id")
                    if not nid or nid in seen:
                        continue
                    seen.add(nid)

                    await send(f"🎯 Найден лот: {format_item(it)}")

                    if self.dry_run:
                        continue

                    try:
                        price = float(it["price"])
                        owner_id = it.get("owner_id")
                        res = await asyncio.to_thread(_buy_once, nid, price, auth, owner_id)
                        await send(f"✅ Покупка отправлена: {format_item(it)}\nОтвет: {res}")
                    except Exception as e:
                        await send(f"Ошибка покупки: {e}")

                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                await send(f"Loop error (Portals): {e}")
                try:
                    auth = await self._get_auth()
                    await send("Portals auth обновлён.")
                except Exception:
                    pass
                await asyncio.sleep(2.0)

        await send("Portals автобайер остановлен.")