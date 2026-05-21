"""Monad chain poller — watches FOR Transfer events to subscribed wallets and
dispatches Telegram notifications matching the @fortytwo_node_bot format."""

import asyncio
import logging
from datetime import datetime, timezone

from telegram.ext import Application

from chain import (
    get_for_balance,
    get_latest_block,
    get_native_balance,
    get_transfer_events,
)
from wallets import chats_for_wallet, get_state, list_watched, set_state

log = logging.getLogger("poller")

SCAN_TX = "https://testnet.monadexplorer.com/tx/"
MAX_BLOCK_RANGE = 9999  # eth_getLogs sanity cap for a single call

# In-memory daily accumulator: { wallet_lower: (date_str_utc, sum_today_float) }
_daily: dict[str, tuple[str, float]] = {}


def _bump_daily(wallet: str, amount: float) -> float:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cur = _daily.get(wallet.lower())
    if cur is None or cur[0] != today:
        new_total = amount
    else:
        new_total = cur[1] + amount
    _daily[wallet.lower()] = (today, new_total)
    return new_total


def _short_addr(addr: str) -> str:
    return f"{addr[:8]}...{addr[-7:]}"


async def _send_notification(
    application: Application,
    event: dict,
    rpc_url: str,
    for_contract: str,
) -> None:
    wallet = event["to"]
    chats = chats_for_wallet(wallet)
    if not chats:
        return

    # Pull live balances after the transfer landed
    try:
        token_balance = await get_for_balance(rpc_url, for_contract, wallet)
    except Exception:
        token_balance = None
    try:
        native_balance = await get_native_balance(rpc_url, wallet)
    except Exception:
        native_balance = None

    daily_total = _bump_daily(wallet, event["amount"])
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def _fmt_num(v: float | None, digits: int = 4) -> str:
        return f"{v:.{digits}f}" if v is not None else "—"

    msg = (
        "🔔 *Notify! New Received FOR Token Distribution*\n\n"
        f"🪙 *Token Amount:* {_fmt_num(event['amount'])} FOR\n"
        f"🟩 *Token Balance:* {_fmt_num(token_balance)} FOR\n"
        f"🟧 *Daily Accumulated:* {_fmt_num(daily_total)} FOR\n"
        f"🏧 *Wallet Address:* `{_short_addr(wallet)}`\n"
        f"🟪 *Current Balance:* {_fmt_num(native_balance)} MONAD\n"
        f"🛰 *Scan Explorer:* [Tx Hash/ID]({SCAN_TX}{event['tx_hash']})\n"
        f"🌐 *Timestamp:* {timestamp}"
    )

    for chat_id in chats:
        try:
            await application.bot.send_message(
                chat_id=chat_id,
                text=msg,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        except Exception as e:
            log.warning(f"failed to DM chat {chat_id}: {e}")


async def poll_loop(
    application: Application,
    rpc_url: str,
    for_contract: str,
    interval: int = 60,
) -> None:
    log.info(f"poller starting (interval={interval}s, contract={for_contract})")

    # Bootstrap last-block cursor at current head so we don't replay history on first run
    last_block_str = get_state("last_block")
    if not last_block_str:
        try:
            current = await get_latest_block(rpc_url)
            set_state("last_block", str(current))
            last_block = current
            log.info(f"poller cursor bootstrapped at block {current}")
        except Exception as e:
            log.exception(f"bootstrap failed: {e}")
            await asyncio.sleep(interval)
            return await poll_loop(application, rpc_url, for_contract, interval)
    else:
        last_block = int(last_block_str)

    while True:
        try:
            wallets = list_watched()
            if not wallets:
                await asyncio.sleep(interval)
                continue

            current_block = await get_latest_block(rpc_url)
            if current_block <= last_block:
                await asyncio.sleep(interval)
                continue

            from_block = last_block + 1
            to_block = min(current_block, from_block + MAX_BLOCK_RANGE)
            addresses = [w["address"] for w in wallets]

            try:
                events = await get_transfer_events(
                    rpc_url, for_contract, addresses, from_block, to_block,
                )
            except Exception as e:
                log.warning(f"eth_getLogs {from_block}-{to_block} failed: {e}")
                await asyncio.sleep(interval)
                continue

            if events:
                log.info(f"blocks {from_block}-{to_block}: {len(events)} transfer event(s)")
            for ev in events:
                try:
                    await _send_notification(application, ev, rpc_url, for_contract)
                except Exception as e:
                    log.exception(f"notify failed for tx {ev['tx_hash']}: {e}")

            last_block = to_block
            set_state("last_block", str(last_block))
        except Exception as e:
            log.exception(f"poll iteration error: {e}")

        await asyncio.sleep(interval)
