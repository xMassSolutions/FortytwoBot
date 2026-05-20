import httpx

ERC20_BALANCE_OF_SELECTOR = "0x70a08231"


async def get_for_balance(rpc_url: str, contract: str, wallet: str) -> float:
    addr = wallet.lower().removeprefix("0x").rjust(64, "0")
    data = ERC20_BALANCE_OF_SELECTOR + addr
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": contract, "data": data}, "latest"],
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(rpc_url, json=payload)
        r.raise_for_status()
        result = r.json()
    if "error" in result:
        raise RuntimeError(f"RPC error: {result['error']}")
    raw_hex = result["result"]
    return int(raw_hex, 16) / 10**18
