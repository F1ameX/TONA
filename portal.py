import os
import time
import asyncio
import random
import logging
import csv
from itertools import islice
from typing import Dict, List, Optional, Set, Callable, Awaitable, Any, Tuple

from portalsmp import search as portals_search
from portalsmp import update_auth as portals_update_auth

logger = logging.getLogger("tona.portals")

class Portals:
    def __init__(
        self, 
        api_id: int, 
        api_hash: str, 
        csv_path: str = "model-backdrop-match.csv",
        request_timeout: float = 5.0
    ) -> None:
        
        self.api_id = api_id
        self.api_hash = api_hash
        self.csv_path = csv_path
        self.request_timeout = request_timeout

        self._auth_cache: Optional[str] = None
        self._auth_ts: float = 0.0
        self._auth_ttl: float = 30 * 60  # 30 mins

        self.max_retries = int(self._get_env("PORTALS_MAX_RETRIES", 2))
        self.backoff_base = float(self._get_env("PORTALS_BACKOFF_BASE", 0.3))
        self.retry_delay = float(self._get_env("PORTALS_RETRY_DELAY", 1.0))
        self.cache_ttl = float(self._get_env("CACHE_TTL", 1.5))

        self.model_to_colors: Dict[str, Set[str]] = {}
        self.models: List[str] = []
        self._search_cache: Dict[str, Tuple[float, List[Dict]]] = {}
        
        self._load_mapping()

    @staticmethod
    def _get_env(key: str, default: Any) -> Any:
        return os.getenv(key, default)


    async def get_auth(self) -> str:
        now = time.time()
        if now - self._auth_ts < self._auth_ttl and self._auth_cache:
            return self._auth_cache
            
        try:
            token = await portals_update_auth(self.api_id, self.api_hash)
            self._auth_cache = token
            self._auth_ts = now
            logger.info("Auth token updated successfully")
            return token
        except Exception as e:
            logger.error(f"Auth update failed: {e}")
            if self._auth_cache:
                logger.warning("Using cached auth token despite error")
                return self._auth_cache
            raise


    def _load_mapping(self) -> None:
        try:
            if not os.path.exists(self.csv_path):
                logger.warning(f"CSV file not found: {self.csv_path}")
                return
                
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    model = row.get('\ufeff"col"', '').lower().strip()
                    backdrop = row.get('name', '').lower().strip()
                    print(row, model, backdrop)
                    if model and backdrop:
                        self.model_to_colors.setdefault(model, set()).add(backdrop)
                        
            self.models = list(sorted(self.model_to_colors.keys()))
            logger.info(f"Mapping loaded: {len(self.models)} models, {sum(len(v) for v in self.model_to_colors.values())} backdrops")
            
        except Exception as e:
            logger.error(f"Failed to load mapping: {e}")
            self.model_to_colors = {}
            self.models = []

    def allowed_colors_for(self, model: str) -> Set[str]:
        return self.model_to_colors.get(model.strip().lower(), set())

    @staticmethod
    def extract_backdrop(item: Dict) -> Optional[str]:
        attributes = item.get("attributes") or []
        for attr in attributes:
            if isinstance(attr, dict) and attr.get("type") == "backdrop":
                value = attr.get("value")
                return value.strip().lower() if isinstance(value, str) else None
        return None

    def _is_item_allowed(self, item: Dict, allowed: Set[str]) -> bool:
        if not allowed:
            return True
            
        backdrop = self.extract_backdrop(item)
        return backdrop is not None and backdrop in allowed

    async def _with_timeout(self, func: Callable, *args, **kwargs) -> Any:
        return await asyncio.wait_for(
            asyncio.to_thread(func, *args, **kwargs),
            timeout=self.request_timeout
        )

    async def _search_with_retries(self, *, model: str, limit: int, auth: str) -> List[Dict]:
        attempt = 0
        last_error = None
        
        while attempt < self.max_retries:
            try:
                result = await self._with_timeout(
                    portals_search,
                    sort="price_asc",
                    limit=limit,
                    gift_name=model,
                    authData=auth
                )
                return result or []
                
            except asyncio.TimeoutError:
                last_error = f"Timeout after {self.request_timeout}s"
                logger.warning(f"Search timeout for {model} (attempt {attempt+1}/{self.max_retries})")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Search error for {model}: {e} (attempt {attempt+1}/{self.max_retries})")

            attempt += 1
            if attempt < self.max_retries:
                delay = (self.backoff_base ** attempt) + random.uniform(0, 0.4)
                await asyncio.sleep(delay)
                
        raise Exception(f"Search failed after {self.max_retries} attempts: {last_error}")

    async def search_multiple_models(self, models: List[str], limit: int = 50) -> Dict[str, List[Dict]]:
        auth = await self.get_auth()
        tasks = []
        current_time = time.time()
        
        models_to_fetch = []
        cached_results = {}
        
        for model in models:
            if model in self._search_cache:
                cache_time, cached_data = self._search_cache[model]
                if current_time - cache_time < self.cache_ttl:
                    cached_results[model] = cached_data
                    continue
            models_to_fetch.append(model)
        
        for model in models_to_fetch:
            task = self._search_with_retries(model=model, limit=limit, auth=auth)
            tasks.append((model, task))
        
        if tasks:
            results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)
            
            for (model, _), result in zip(tasks, results):
                if not isinstance(result, Exception):
                    self._search_cache[model] = (current_time, result)
                    cached_results[model] = result
        
        filtered_results = {}
        for model, result in cached_results.items():
            if isinstance(result, Exception):
                logger.error(f"Search failed for {model}: {result}")
                filtered_results[model] = []
            else:
                allowed = self.allowed_colors_for(model)
                filtered_items = [item for item in result if self._is_item_allowed(item, allowed)]
                filtered_results[model] = filtered_items
        
        return filtered_results

    async def search_filtered(self, model: str, limit: int = 50) -> List[Dict]:
        try:
            results = await self.search_multiple_models([model], limit=limit)
            return results.get(model, [])
            
        except Exception as e:
            logger.error(f"Search filtered failed for {model}: {e}")
            return []

    async def optimized_loop(
        self,
        on_items: Callable[[Dict[str, List[Dict]]], Awaitable[None]],
        sleep_between: float = 0.1,
        limit: int = 50,
        batch_size: int = 5,
        should_continue: Optional[Callable[[], bool]] = None,
    ) -> None:
        if not self.models:
            logger.error("No models loaded; loop aborted.")
            return

        logger.info(f"Starting optimized loop with {len(self.models)} models, batch size {batch_size}")
        
        model_batches = []
        for i in range(0, len(self.models), batch_size):
            batch = list(islice(self.models, i, i + batch_size))
            model_batches.append(batch)
        
        iteration = 0
        while should_continue is None or should_continue():
            iteration += 1
            batch = model_batches[iteration % len(model_batches)]
            
            try:
                results = await self.search_multiple_models(batch, limit=limit)
                await on_items(results)
                
            except Exception as e:
                logger.error(f"Batch loop error: {e}")
            
            await asyncio.sleep(sleep_between)

        logger.info("Optimized loop stopped")