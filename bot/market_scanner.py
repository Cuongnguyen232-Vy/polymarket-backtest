"""
market_scanner.py — Module 1: Polymarket Market Scanner
═══════════════════════════════════════════════════════════════
Scans Polymarket Gamma API to find eligible markets matching
the PolyM strategy parameters from the reverse-engineering report.

Report References:
  §2.1 — Market Demographics: ONLY "Crypto Up or Down" 5/15-min
  §2.1 — Price Range: $0.30 - $0.70 (70.7% of PolyM trades)
  §5   — Volume Filter: > $50,000
  §4.3 — Depth Filter: Avoid Illiquidity Traps
  
API Endpoints:
  REST: gamma-api.polymarket.com/events (scan new markets, 1/min)
  REST: clob.polymarket.com/book (orderbook depth check)
═══════════════════════════════════════════════════════════════
"""

import re
import time
import asyncio
import aiohttp
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional

from config import (
    TARGET_KEYWORDS, ENTRY_PRICE_MIN, ENTRY_PRICE_MAX,
    MIN_MARKET_VOLUME, MIN_ORDERBOOK_DEPTH,
    PREFERRED_TIMEFRAME_MINUTES, GAMMA_API_BASE, CLOB_API_BASE,
    SCAN_INTERVAL_SEC, MAX_CONCURRENT_POSITIONS,
)

logger = logging.getLogger("PolyM.scanner")


# ─── Data Models ─────────────────────────────────────────────

@dataclass
class Market:
    """Represents a single eligible Polymarket market."""
    id: str
    event_title: str
    question: str
    asset: str                       # BTC, ETH, SOL, XRP
    timeframe_minutes: int           # 5 or 15
    yes_token_id: str
    no_token_id: str
    yes_price: float
    no_price: float
    volume: float
    end_date: Optional[str] = None
    orderbook_depth_yes: float = 0.0
    orderbook_depth_no: float = 0.0
    spread: float = 0.0
    is_eligible: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Scanner Class ───────────────────────────────────────────

class MarketScanner:
    """
    Scans Polymarket for markets matching PolyM strategy criteria.
    
    PolyM Filter Pipeline (Report §2.1 + §5):
    1. Keyword filter  → "Crypto Up or Down" only
    2. Asset filter    → BTC, ETH, SOL, XRP
    3. Timeframe       → 15-min (90.3%) or 5-min
    4. Price range     → $0.30 - $0.70
    5. Volume          → > $50,000
    6. Orderbook depth → > $5,000 opposite side
    """

    def __init__(self, db):
        self.db = db
        self.session: Optional[aiohttp.ClientSession] = None
        self._scan_count = 0

    async def _ensure_session(self):
        """Lazy init aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )

    async def close(self):
        """Close HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()

    # ─── Main Scan ───────────────────────────────────────────

    async def scan_markets(self) -> list[Market]:
        """
        Full scan pipeline:
        1. Fetch active "Up or Down" markets from Gamma /markets API
        2. Filter by PolyM criteria (asset, price, accepting orders)
        3. Fetch orderbooks for eligible markets
        4. Save to database
        5. Return list of eligible Market objects
        
        CRITICAL FIX: Uses /markets endpoint (not /events) because the
        /events endpoint does NOT reliably return short-duration 
        "Crypto Up or Down" minute markets. Only /markets with 
        order=createdAt returns them correctly.
        """
        await self._ensure_session()
        self._scan_count += 1

        try:
            # Step 1: Fetch markets directly
            raw_markets = await self._fetch_markets()
            if not raw_markets:
                logger.info(
                    f"Scan #{self._scan_count}: No up-or-down markets "
                    f"found (markets may not be active at this hour)"
                )
                return []

            # Step 2: Filter through PolyM pipeline
            candidates = self._filter_raw_markets(raw_markets)
            logger.info(
                f"Scan #{self._scan_count}: {len(raw_markets)} raw → "
                f"{len(candidates)} candidates after filters"
            )

            if not candidates:
                return []

            # Step 3: Fetch orderbooks and final depth filter
            eligible = await self._enrich_with_orderbooks(candidates)
            logger.info(
                f"  → {len(eligible)} markets passed depth filter"
            )

            # Step 4: Save to database
            for market in eligible:
                market.is_eligible = True
                try:
                    self.db.upsert_market({
                        "id": market.id,
                        "event_title": market.event_title,
                        "question": market.question,
                        "asset": market.asset,
                        "timeframe_minutes": market.timeframe_minutes,
                        "yes_token_id": market.yes_token_id,
                        "no_token_id": market.no_token_id,
                        "yes_price": market.yes_price,
                        "no_price": market.no_price,
                        "volume": market.volume,
                        "end_date": market.end_date,
                        "orderbook_depth_yes": market.orderbook_depth_yes,
                        "orderbook_depth_no": market.orderbook_depth_no,
                        "spread": market.spread,
                        "is_eligible": True,
                    })
                except Exception as e:
                    logger.error(f"DB upsert failed for {market.id}: {e}")

            self.db.log("INFO", "scanner", f"Scan #{self._scan_count}", {
                "raw_markets": len(raw_markets),
                "candidates": len(candidates),
                "eligible": len(eligible),
            })

            return eligible

        except Exception as e:
            logger.error(f"Scan failed: {e}")
            self.db.log("ERROR", "scanner", f"Scan failed: {str(e)}")
            return []

    # ─── Step 1: Fetch Markets (Slug-Based Real-Time Discovery) ─

    # Slug prefixes for each crypto asset
    CRYPTO_SLUG_MAP = {
        "BTC": "btc",
        "ETH": "eth",
        "SOL": "sol",
        "XRP": "xrp",
    }

    async def _fetch_markets(self) -> list:
        """
        Discover active "Up or Down" markets using slug-based timestamp
        construction (primary) + Gamma listing API (fallback).

        CRITICAL FIX: The Gamma listing API (?active=true) does NOT
        return currently-active Up/Down 5-min/15-min crypto markets.
        It only returns markets scheduled 24+ hours in the future.
        
        The real-time markets are discoverable by constructing slug
        patterns from epoch timestamps:
          slug = "{crypto}-updown-{window}m-{start_epoch}"
        and querying GET /events?slug={slug}
        """
        await self._ensure_session()
        all_markets = []
        seen_ids = set()
        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()

        # ── Primary: Slug-based real-time discovery ──
        try:
            slug_markets = await self._fetch_markets_by_slug(now_ts)
            for m in slug_markets:
                mid = m.get("conditionId") or m.get("id", "")
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    all_markets.append(m)
        except Exception as e:
            logger.error(f"Slug-based scan error: {e}")

        # ── Fallback: Gamma listing API (for future markets) ──
        try:
            listing_markets = await self._fetch_markets_listing(now)
            for m in listing_markets:
                mid = m.get("conditionId") or m.get("id", "")
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    all_markets.append(m)
        except Exception as e:
            logger.debug(f"Listing fallback error: {e}")

        return all_markets

    async def _fetch_markets_by_slug(self, now_ts: float) -> list:
        """
        Build slug candidates for current time windows and fetch
        market data from Gamma /events?slug=... endpoint.
        
        Returns list of raw market dicts compatible with _filter_raw_markets().
        """
        import json as _json

        candidate_slugs = []
        windows = [("5m", 300), ("15m", 900)]

        for asset, prefix in self.CRYPTO_SLUG_MAP.items():
            for win_label, win_secs in windows:
                base = int(now_ts) - (int(now_ts) % win_secs)
                # Check: previous window, current, and next 2
                for offset in range(-1, 3):
                    epoch = base + (offset * win_secs)
                    candidate_slugs.append(f"{prefix}-updown-{win_label}-{epoch}")

        # Fetch all slugs concurrently with rate limit
        semaphore = asyncio.Semaphore(10)
        results = []

        async def _fetch_one(slug: str):
            async with semaphore:
                try:
                    url = f"{GAMMA_API_BASE}/events?slug={slug}"
                    async with self.session.get(url) as resp:
                        if resp.status != 200:
                            return []
                        data = await resp.json()
                        if not data or not isinstance(data, list):
                            return []

                    markets_out = []
                    for event in data:
                        title = event.get("title", "")
                        if "Up or Down" not in title:
                            continue

                        # Convert event format → raw market format
                        # (compatible with _filter_raw_markets)
                        event_markets = event.get("markets", [])
                        for sub_m in event_markets:
                            # Ensure it looks like a /markets response
                            sub_m["question"] = sub_m.get("question", title)
                            sub_m["endDate"] = sub_m.get("endDate", event.get("endDate", ""))
                            sub_m["acceptingOrders"] = True
                            sub_m["enableOrderBook"] = True
                            # Carry volume from event level if missing
                            if not sub_m.get("volume"):
                                sub_m["volume"] = event.get("volume", "0")
                            markets_out.append(sub_m)

                    return markets_out
                except asyncio.TimeoutError:
                    return []
                except Exception as e:
                    logger.debug(f"Slug fetch {slug}: {e}")
                    return []

        tasks = [_fetch_one(s) for s in candidate_slugs]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        all_slug_markets = []
        for r in batch_results:
            if isinstance(r, list):
                all_slug_markets.extend(r)

        logger.debug(f"Slug scan: {len(candidate_slugs)} slugs → {len(all_slug_markets)} markets")
        return all_slug_markets

    async def _fetch_markets_listing(self, now: datetime) -> list:
        """
        Fallback: Gamma listing API for future-scheduled markets.
        These won't be currently active but may pass orderbook checks.
        """
        all_markets = []

        for offset in range(0, 200, 100):
            url = f"{GAMMA_API_BASE}/markets"
            params = {
                "active": "true",
                "closed": "false",
                "limit": 100,
                "offset": offset,
                "order": "createdAt",
                "ascending": "false",
            }

            try:
                async with self.session.get(url, params=params) as resp:
                    if resp.status == 429:
                        logger.warning("Gamma /markets RATE LIMITED (429)")
                        break
                    if resp.status != 200:
                        break

                    markets = await resp.json()
                    if not markets:
                        break

                    for m in markets:
                        q = m.get("question", "").lower()
                        if "up or down" not in q:
                            continue
                        if not m.get("acceptingOrders", False):
                            continue
                        if not m.get("enableOrderBook", False):
                            continue

                        end_date_str = m.get("endDate", "")
                        if end_date_str:
                            try:
                                end_dt = datetime.fromisoformat(
                                    end_date_str.replace("Z", "+00:00")
                                )
                                hours_until_end = (end_dt - now).total_seconds() / 3600
                                if hours_until_end > 24 or hours_until_end < -0.1:
                                    continue
                            except (ValueError, TypeError):
                                pass

                        all_markets.append(m)

                    await asyncio.sleep(0.15)

            except Exception as e:
                logger.debug(f"Listing API error: {e}")
                break

        return all_markets

    # ─── Step 2: Filter Pipeline (Market-level) ───────────────

    def _filter_raw_markets(self, raw_markets: list) -> list[Market]:
        """
        Apply PolyM filter pipeline to raw /markets API results.
        Returns list of Market candidates.
        
        Pipeline (Report §2.1 + §5):
        1. Keyword → already pre-filtered in _fetch_markets
        2. Asset   → BTC, ETH, SOL, XRP (Report §2.1)
        3. Price   → $0.30 - $0.70 (if prices available)
        4. Timeframe extraction
        
        NOTE: Volume filter is relaxed for minute markets because
        they start with $0 volume and gain liquidity as settlement
        approaches. The orderbook depth filter (Step 3) is the 
        real gatekeeper.
        """
        candidates = []
        skip_no_asset = 0
        skip_not_accepting = 0
        skip_parse_fail = 0
        skip_price_range = 0

        for mkt_data in raw_markets:
            question = mkt_data.get("question", "")
            
            # ── Filter 1: Extract asset (Report §2.1) ──
            asset = self._extract_asset(question)
            if not asset:
                skip_no_asset += 1
                continue

            # ── Filter 2: Must be accepting orders ──
            if not mkt_data.get("acceptingOrders", False):
                skip_not_accepting += 1
                continue

            # Parse into Market dataclass
            market = self._parse_market_direct(mkt_data, asset)
            if market is None:
                skip_parse_fail += 1
                continue

            # ── Filter 3: Price Range (Report §2.1) ──
            # Only apply if prices are available (> 0)
            # New markets may have $0 price before first trade
            if market.yes_price > 0:
                if not (ENTRY_PRICE_MIN <= market.yes_price <= ENTRY_PRICE_MAX):
                    if market.no_price > 0 and not (
                        ENTRY_PRICE_MIN <= market.no_price <= ENTRY_PRICE_MAX
                    ):
                        skip_price_range += 1
                        continue

            candidates.append(market)

        if skip_no_asset + skip_price_range > 0:
            logger.debug(
                f"Filter skips: no_asset={skip_no_asset}, "
                f"not_accepting={skip_not_accepting}, "
                f"parse_fail={skip_parse_fail}, "
                f"price_range={skip_price_range}"
            )

        return candidates

    def _parse_market_direct(
        self, mkt_data: dict, asset: str
    ) -> Optional[Market]:
        """
        Parse a raw /markets API result into a Market dataclass.
        
        The /markets endpoint has a DIFFERENT structure from /events:
        - Token IDs are in 'clobTokenIds' (JSON string array)
        - Prices are in 'outcomePrices' (JSON string array)
        - 'tokens' array may be EMPTY for new markets
        """
        try:
            import json as _json

            # Try 'tokens' array first (standard format)
            tokens = mkt_data.get("tokens", [])
            
            if tokens and len(tokens) >= 2:
                # Standard format with embedded tokens
                yes_token_id = tokens[0].get("token_id", "")
                no_token_id = tokens[1].get("token_id", "")
                yes_price = float(tokens[0].get("price", 0) or 0)
                no_price = float(tokens[1].get("price", 0) or 0)
                
                # Fallback to outcomePrices if token prices are 0
                if yes_price <= 0 and no_price <= 0:
                    prices_raw = mkt_data.get("outcomePrices", "[]")
                    if isinstance(prices_raw, str):
                        prices = _json.loads(prices_raw)
                    else:
                        prices = prices_raw
                    yes_price = float(prices[0]) if prices else 0.50
                    no_price = float(prices[1]) if len(prices) > 1 else 0.50
            else:
                # /markets format: clobTokenIds + outcomePrices
                clob_raw = mkt_data.get("clobTokenIds", "[]")
                if isinstance(clob_raw, str):
                    clob_ids = _json.loads(clob_raw)
                else:
                    clob_ids = clob_raw
                
                if len(clob_ids) < 2:
                    return None
                
                yes_token_id = clob_ids[0]
                no_token_id = clob_ids[1]
                
                # Parse prices
                prices_raw = mkt_data.get("outcomePrices", "[]")
                if isinstance(prices_raw, str):
                    prices = _json.loads(prices_raw)
                else:
                    prices = prices_raw
                
                yes_price = float(prices[0]) if prices else 0
                no_price = float(prices[1]) if len(prices) > 1 else 0

            if not yes_token_id or not no_token_id:
                return None

            question = mkt_data.get("question", "")
            timeframe = self._extract_timeframe(question)
            volume = float(mkt_data.get("volume", 0) or 0)

            return Market(
                id=mkt_data.get("id", ""),
                event_title=question,
                question=question,
                asset=asset,
                timeframe_minutes=timeframe,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
                yes_price=yes_price,
                no_price=no_price,
                volume=volume,
                end_date=mkt_data.get("endDate"),
            )
        except (ValueError, KeyError, TypeError) as e:
            logger.debug(f"Failed to parse market: {e}")
            return None

    def _parse_market(self, market_data: dict, event_title: str,
                      asset: str, volume: float) -> Optional[Market]:
        """Parse a raw market dict into a Market dataclass."""
        try:
            tokens = market_data.get("tokens", [])
            if len(tokens) < 2:
                return None

            # Token 0 = YES, Token 1 = NO
            yes_token = tokens[0]
            no_token = tokens[1]

            yes_price = float(yes_token.get("price", 0) or 0)
            no_price = float(no_token.get("price", 0) or 0)

            # Fallback to outcomePrices for dormant markets
            if yes_price <= 0 and no_price <= 0:
                import json as _json
                prices_raw = market_data.get("outcomePrices", "[]")
                if isinstance(prices_raw, str):
                    prices = _json.loads(prices_raw)
                else:
                    prices = prices_raw
                yes_price = float(prices[0]) if prices else 0.50
                no_price = float(prices[1]) if len(prices) > 1 else 0.50

            question = market_data.get("question", event_title)
            timeframe = self._extract_timeframe(question)

            return Market(
                id=market_data.get("id", ""),
                event_title=event_title,
                question=question,
                asset=asset,
                timeframe_minutes=timeframe,
                yes_token_id=yes_token.get("token_id", ""),
                no_token_id=no_token.get("token_id", ""),
                yes_price=yes_price,
                no_price=no_price,
                volume=volume,
                end_date=market_data.get("endDate"),
            )
        except (ValueError, KeyError, TypeError) as e:
            logger.debug(f"Failed to parse market: {e}")
            return None

    # ─── Step 3: Orderbook Enrichment ────────────────────────

    async def _enrich_with_orderbooks(
        self, candidates: list[Market]
    ) -> list[Market]:
        """
        Fetch orderbooks for candidates and filter by depth.
        
        Report §4.3 Fix: "Illiquidity Trap — liquidity at $0.425
        evaporates instantly → Zombie Orders"
        → Only trade markets with sufficient depth
        """
        eligible = []

        for market in candidates:
            try:
                # Fetch YES orderbook
                yes_book = await self._fetch_orderbook(market.yes_token_id)

                if yes_book:
                    market.orderbook_depth_yes = yes_book["total_bid_depth"]
                    # Only update price if orderbook bid is reasonable
                    # (dormant markets have best_bid=$0.01 garbage)
                    ob_bid = yes_book.get("best_bid", 0)
                    if ob_bid > 0.10:
                        market.yes_price = ob_bid
                    market.spread = yes_book.get("spread", 0)

                # Fetch NO orderbook
                no_book = await self._fetch_orderbook(market.no_token_id)

                if no_book:
                    market.orderbook_depth_no = no_book["total_bid_depth"]
                    ob_bid = no_book.get("best_bid", 0)
                    if ob_bid > 0.10:
                        market.no_price = ob_bid

                # ── Filter: Depth (Report §5 / §4.3 Fix) ──
                # At least one side must have depth > MIN_ORDERBOOK_DEPTH
                max_depth = max(
                    market.orderbook_depth_yes,
                    market.orderbook_depth_no
                )
                if max_depth >= MIN_ORDERBOOK_DEPTH:
                    eligible.append(market)
                else:
                    logger.debug(
                        f"Skipped {market.asset} market: "
                        f"depth ${max_depth:,.0f} < ${MIN_ORDERBOOK_DEPTH:,}"
                    )
                    self.db.log("INFO", "scanner", f"Market skipped: low depth", {
                        "asset": market.asset,
                        "depth": round(max_depth, 0),
                        "min_required": MIN_ORDERBOOK_DEPTH,
                        "question": market.question[:60],
                    })

                # Rate limit: small delay between orderbook calls
                await asyncio.sleep(0.15)

            except Exception as e:
                logger.error(
                    f"Orderbook fetch failed for {market.id}: {e}"
                )
                self.db.log("ERROR", "scanner", f"Orderbook fetch failed: {e}", {
                    "market_id": market.id, "asset": market.asset
                })
                continue

        return eligible

    async def _fetch_orderbook(self, token_id: str) -> Optional[dict]:
        """
        Fetch orderbook from Polymarket CLOB API.
        
        Returns:
            {
                "bids": [...],
                "asks": [...],
                "best_bid": float,
                "best_ask": float,
                "spread": float,
                "total_bid_depth": float (in USD),
                "total_ask_depth": float (in USD),
            }
        """
        if not token_id:
            return None

        url = f"{CLOB_API_BASE}/book"
        params = {"token_id": token_id}

        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status == 429:
                    logger.warning(f"CLOB orderbook RATE LIMITED (429) for {token_id[:16]}...")
                    return None
                if resp.status != 200:
                    return None

                data = await resp.json()

                bids = data.get("bids", [])
                asks = data.get("asks", [])

                # Calculate depth in USD
                total_bid_depth = sum(
                    float(b.get("size", 0)) * float(b.get("price", 0))
                    for b in bids
                )
                total_ask_depth = sum(
                    float(a.get("size", 0)) * float(a.get("price", 0))
                    for a in asks
                )

                best_bid = float(bids[0]["price"]) if bids else 0
                best_ask = float(asks[0]["price"]) if asks else 0
                spread = best_ask - best_bid if (best_ask and best_bid) else 0

                return {
                    "bids": bids,
                    "asks": asks,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread": spread,
                    "total_bid_depth": total_bid_depth,
                    "total_ask_depth": total_ask_depth,
                }

        except Exception as e:
            logger.debug(f"Orderbook fetch error for {token_id}: {e}")
            return None

    # ─── Helpers ─────────────────────────────────────────────

    @staticmethod
    def _extract_asset(title: str) -> Optional[str]:
        """Extract crypto asset from event title."""
        title_lower = title.lower()
        if "bitcoin" in title_lower:
            return "BTC"
        elif "ethereum" in title_lower:
            return "ETH"
        elif "solana" in title_lower:
            return "SOL"
        elif "xrp" in title_lower:
            return "XRP"
        return None

    @staticmethod
    def _extract_timeframe(question: str) -> int:
        """
        Extract timeframe in minutes from market question.
        
        Example questions:
        "Will BTC be up... 10:00AM-10:15AM ET" → 15 min
        "Will ETH be up... 10:00AM-10:05AM ET" → 5 min
        """
        # Try to find time range like "10:00AM-10:15AM"
        pattern = r"(\d{1,2}):(\d{2})\s*([AP]M)\s*[-–]\s*(\d{1,2}):(\d{2})\s*([AP]M)"
        match = re.search(pattern, question, re.IGNORECASE)

        if match:
            h1, m1, p1 = int(match.group(1)), int(match.group(2)), match.group(3).upper()
            h2, m2, p2 = int(match.group(4)), int(match.group(5)), match.group(6).upper()

            # Convert to 24h
            if p1 == "PM" and h1 != 12:
                h1 += 12
            if p1 == "AM" and h1 == 12:
                h1 = 0
            if p2 == "PM" and h2 != 12:
                h2 += 12
            if p2 == "AM" and h2 == 12:
                h2 = 0

            diff = (h2 * 60 + m2) - (h1 * 60 + m1)
            if diff < 0:
                diff += 24 * 60  # Cross midnight

            return diff

        # Default to 15-min (90.3% of PolyM trades)
        return PREFERRED_TIMEFRAME_MINUTES


# ─── Quick Test ──────────────────────────────────────────────

async def _test():
    """Test scanner against live Polymarket API."""
    from db import Database

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    )

    db = Database()
    scanner = MarketScanner(db)

    print("🔍 Scanning Polymarket for PolyM-eligible markets...\n")

    markets = await scanner.scan_markets()

    if markets:
        print(f"\n✅ Found {len(markets)} eligible markets:\n")
        print(f"{'Asset':<6} {'YES $':<8} {'NO $':<8} {'Vol $':<12} "
              f"{'Depth YES':<12} {'Depth NO':<12} {'TF':<4} Title")
        print("─" * 100)

        for m in markets:
            print(
                f"{m.asset:<6} "
                f"${m.yes_price:<7.3f} "
                f"${m.no_price:<7.3f} "
                f"${m.volume:<11,.0f} "
                f"${m.orderbook_depth_yes:<11,.0f} "
                f"${m.orderbook_depth_no:<11,.0f} "
                f"{m.timeframe_minutes:<4} "
                f"{m.event_title[:40]}"
            )
    else:
        print("⚠️  No eligible markets found right now.")
        print("   (Markets may not be active at this hour)")

    await scanner.close()
    print("\n🏁 Scanner test complete")


if __name__ == "__main__":
    asyncio.run(_test())
