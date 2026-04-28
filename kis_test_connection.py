# ============================================================
#  Korea Investment paper API connection test
#  Tests token, quote, and balance. It does not place orders.
# ============================================================

from __future__ import annotations

from kis_client import KisClient, load_config_from_env


def main() -> None:
    client = KisClient(load_config_from_env())

    print("=" * 64)
    print("  KIS Paper API Connection Test")
    print("=" * 64)
    print(f"Environment: {client.config.env}")
    print(f"Orders enabled: {client.config.enable_orders}")
    print(f"Account: {client.config.account_no}-{client.config.account_product_code}")

    token = client.issue_access_token()
    print(f"Token: OK ({token[:8]}...)")

    quote = client.get_current_price("005930")
    output = quote.get("output", {})
    price = output.get("stck_prpr", "")
    print(f"Quote test: OK, 005930 current price = {price}")

    try:
        balance = client.get_balance()
        items = balance.get("output1", [])
        summary = balance.get("output2", [])
        print(f"Balance test: OK, holdings = {len(items)}")
        if summary:
            cash = summary[0].get("dnca_tot_amt", "")
            total = summary[0].get("tot_evlu_amt", "")
            print(f"Cash: {cash}")
            print(f"Total evaluation: {total}")
    except Exception as exc:
        print("Balance test: FAILED")
        print(exc)
        print("Check whether the paper account product code is correct. It is often 01, but your account may differ.")

    print("=" * 64)
    print("Connection test completed. No orders were placed.")


if __name__ == "__main__":
    main()
