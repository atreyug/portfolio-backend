import asyncio
from providers.mutual_funds import MutualFundProvider
from utils.mutual_fund_calculator import compute_nav_performance

async def main():
    p = MutualFundProvider()

    r = await p.resolve_scheme("HDFC Flexi Cap Fund - Direct Plan - Growth")
    print("resolved:", r.get("resolved"), r.get("scheme_code"), r.get("scheme_name"))
    if not r.get("resolved"):
        print(r); return

    h = await p.get_nav_history(r["scheme_code"])
    print("rows:", h.get("count"), "latest:", h.get("latest_date"), "stale:", h.get("is_stale"))

    perf = compute_nav_performance(h["records"])
    print({k: perf[k] for k in ("latest_nav", "return_1y_pct", "cagr_3y_pct", "cagr_5y_pct")})
    await p.client.aclose()

asyncio.run(main())