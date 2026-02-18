import asyncio
import sys
from hunter import hunt_emails_on_web

# Force Windows event loop policy
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

async def main():
    print("Running hunter validation...")
    try:
        # Pass a domain to test both Crawler (Phase 1) and Bing (Phase 2) paths
        results = await hunt_emails_on_web("opentreinamentos.com.br")
        print(f"Validation success! Found {len(results)} leads.")
        for r in results:
            print(r)
    except Exception as e:
        print(f"CRASHED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
