import argparse
from market_hedger import MarketHedger

def main():
    parser = argparse.ArgumentParser(description="Short Russell 2000 index via IWM to hedge portfolio.")
    parser.add_argument(
        "--type", 
        choices=["put", "short", "synthetic"], 
        default="put", 
        help="Hedging Type: 'put' (Protective OTM Put Option, recommended), 'short' (Physical ETF Short Sale), 'synthetic' (Synthetic Short Options)"
    )
    parser.add_argument("--qty", type=int, default=1, help="Quantity: Shares for 'short', Contracts for 'put'/'synthetic' (1 Contract = 100 shares)")
    parser.add_argument("--otm", type=float, default=5.0, help="Out-Of-The-Money distance in % for protective put (default: 5.0%)")
    args = parser.parse_args()

    hedger = MarketHedger("IWM")
    print(f"Executing Russell 2000 Short Hedge using IWM (Type: {args.type.upper()}, Qty: {args.qty})...")
    
    if args.type == "short":
        success = hedger.execute_physical_short(qty=args.qty)
    elif args.type == "synthetic":
        success = hedger.execute_synthetic_short(qty=args.qty)
    else:
        success = hedger.execute_protective_put(otm_pct=args.otm, qty=args.qty)
        
    if success:
        print("Russell 2000 Short position placed successfully.")
    else:
        print("Error: Russell 2000 Short position execution failed.")

if __name__ == "__main__":
    main()
