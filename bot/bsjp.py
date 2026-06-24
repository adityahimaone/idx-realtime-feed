"""
🌙 BSJP (Closing Auction) Signal — 14:30 WIB
Deteksi saham dengan CPR tinggi, VCC, net foreign positif menjelang closing.
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.data_pipeline import get_watchlist_tickers, scan_all, now_wib_str, get_ihsg_status
from data.fetchers import safe_float
from data.scoring import bsjp_score, bsjp_tier, is_bsjp_entry_valid
from bot.telegram import send_telegram


async def run_and_send():
    tickers = get_watchlist_tickers()
    if not tickers:
        await send_telegram("⚠️ Watchlist kosong.")
        return

    ihsg_info = get_ihsg_status()
    results = await scan_all(tickers[:40])

    bsjp_candidates = []
    for r in results:
        price = safe_float(r["live"]["last"])
        high = safe_float(r["live"].get("high", price))
        low = safe_float(r["live"].get("low", price))
        chg = r["chg_pct"]
        volume = safe_float(r["live"].get("volume", 0))

        # CPR
        cpr_val = round((price - low) / (high - low) * 100, 1) if high > low else 50.0
        if cpr_val < 50:
            continue

        # VCC — proxy: volume ratio close to market close (simplified: assume VCC ~ vol spike * 0.3)
        # Real VCC needs tick data. Use vol_spike * 15 as proxy.
        vcc_proxy = min(r["vol_spike"] * 15, 60)
        if vcc_proxy < 25:
            continue

        net_foreign = safe_float(r["live"].get("foreign_buy", 0)) - safe_float(r["live"].get("foreign_sell", 0))
        above_vwap = chg > 0

        sig = {
            "cpr": cpr_val,
            "change_pct": chg,
            "vcc": vcc_proxy,
            "net_foreign_lot": net_foreign,
            "pre_close_momentum": chg * 0.5,  # simplified
            "close_vs_vwap": 0.5 if above_vwap else -0.5,
        }

        score = bsjp_score(sig, ihsg_info)
        tier = bsjp_tier(score)
        valid_check = is_bsjp_entry_valid(sig, score)

        if score >= 40:
            bsjp_candidates.append({
                "ticker": r["ticker"],
                "score": score,
                "tier": tier,
                "cpr": cpr_val,
                "vcc": vcc_proxy,
                "net_foreign": net_foreign,
                "valid": valid_check["valid"],
                "price": price,
            })

    if not bsjp_candidates:
        msg = f"🌙 *BSJP Closing* — {now_wib_str()}\n\nTidak ada kandidat BSJP saat ini. Semua CPR < 50% atau sinyal lemah.\n\n#BSJP #IDX"
        print(msg)
        return

    prime = [c for c in bsjp_candidates if "Prime BSJP" in c["tier"]]
    good = [c for c in bsjp_candidates if "Good BSJP" in c["tier"]]
    watch = [c for c in bsjp_candidates if "Watchlist" in c["tier"]]

    parts = [f"🌙 *BSJP Closing Auction*"]
    parts.append(f"📅 {now_wib_str()}")
    parts.append(f"🟢 IHSG: {ihsg_info['chg_pct']:+.2f}% | CPR {ihsg_info['cpr']:.0f}%")
    parts.append(f"📡 {len(bsjp_candidates)} candidates")
    parts.append("")

    if prime:
        parts.append(f"*🌙 Prime BSJP* ({len(prime)}):")
        for c in sorted(prime, key=lambda x: x["score"], reverse=True)[:5]:
            valid_tag = "✅" if c["valid"] else "❌"
            parts.append(f"• {valid_tag} *{c['ticker']}* Score {c['score']:.0f} | IDR {c['price']:,.0f}")
            parts.append(f"  CPR {c['cpr']:.0f}% | VCC {c['vcc']:.0f}% | NetF {c['net_foreign']:+,.0f}")
        parts.append("")

    if good:
        parts.append(f"*✅ Good BSJP* ({len(good)}):")
        for c in sorted(good, key=lambda x: x["score"], reverse=True)[:5]:
            parts.append(f"• *{c['ticker']}* Score {c['score']:.0f} | CPR {c['cpr']:.0f}%")
        parts.append("")

    if watch:
        parts.append(f"👁️ Watchlist: {', '.join(c['ticker'] for c in watch[:6])}")

    msg = "\n".join(parts) + "\n\n#BSJP #IDX"
    print(msg)
    return msg
