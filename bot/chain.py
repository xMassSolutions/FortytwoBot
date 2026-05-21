"""Monad RPC helpers — balances, log scans, generic eth_call."""

from typing import Any

import httpx

ERC20_BALANCE_OF_SELECTOR = "0x70a08231"
# keccak256("Transfer(address,address,uint256)")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


async def rpc_call(rpc_url: str, method: str, params: list[Any], timeout: float = 15.0) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(rpc_url, json=payload)
        r.raise_for_status()
        result = r.json()
    if "error" in result:
        raise RuntimeError(f"RPC error: {result['error']}")
    return result["result"]


async def get_for_balance(rpc_url: str, contract: str, wallet: str) -> float:
    addr = wallet.lower().removeprefix("0x").rjust(64, "0")
    data = ERC20_BALANCE_OF_SELECTOR + addr
    res = await rpc_call(rpc_url, "eth_call", [{"to": contract, "data": data}, "latest"])
    return int(res, 16) / 10**18


async def get_native_balance(rpc_url: str, wallet: str) -> float:
    """Return native MONAD balance in MONAD (18 decimals)."""
    res = await rpc_call(rpc_url, "eth_getBalance", [wallet, "latest"])
    return int(res, 16) / 10**18


async def get_latest_block(rpc_url: str) -> int:
    res = await rpc_call(rpc_url, "eth_blockNumber", [])
    return int(res, 16)


async def get_block_timestamp(rpc_url: str, block_number: int) -> int:
    res = await rpc_call(rpc_url, "eth_getBlockByNumber", [hex(block_number), False])
    return int(res["timestamp"], 16) if res and res.get("timestamp") else 0


async def get_transfer_events(
    rpc_url: str,
    contract: str,
    to_addresses: list[str],
    from_block: int,
    to_block: int | str = "latest",
) -> list[dict]:
    """ERC-20 Transfer events with `to` matching any of `to_addresses`.

    Returns newest-last list of dicts: {from, to, amount, tx_hash, block_number, log_index}.
    """
    if not to_addresses:
        return []
    to_topics = ["0x" + a.lower().removeprefix("0x").rjust(64, "0") for a in to_addresses]
    params = [{
        "address": contract,
        "topics": [TRANSFER_TOPIC, None, to_topics],
        "fromBlock": hex(from_block),
        "toBlock": to_block if to_block == "latest" else hex(to_block),
    }]
    res = await rpc_call(rpc_url, "eth_getLogs", params)
    out: list[dict] = []
    for log in res:
        out.append({
            "from": "0x" + log["topics"][1][-40:],
            "to": "0x" + log["topics"][2][-40:],
            "amount": int(log["data"], 16) / 10**18,
            "tx_hash": log["transactionHash"],
            "block_number": int(log["blockNumber"], 16),
            "log_index": int(log["logIndex"], 16),
        })
    return out
