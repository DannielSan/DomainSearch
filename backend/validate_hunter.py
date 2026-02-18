import asyncio
import sys
from hunter import hunt_emails_on_web

# Force Windows event loop policy
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

async def main():
    print("Running hunter validation...")
    try:
        domains = ["opentreinamentos.com.br", "gtap.com.br"]
        for domain in domains:
            print(f"\n--- VALIDANDO: {domain} ---")
            results = await hunt_emails_on_web(domain)
            print(f"✅ Found {len(results)} leads for {domain}.")
            for r in results[:5]:  # Show just top 5
                print(f"   - {r['name']} ({r['email']}) [{r['role']}]")
    except Exception as e:
        print(f"CRASHED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
