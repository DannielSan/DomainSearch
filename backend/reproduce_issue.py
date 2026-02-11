import asyncio
from hunter import hunt_emails_on_web

# Force Windows event loop policy
import sys
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

async def main():
    domain = "opentreinamentos.com.br"
    print(f"Running hunter for {domain}...")
    results = await hunt_emails_on_web(domain)
    print("\n--- RESULTS ---")
    for r in results:
        print(r)

if __name__ == "__main__":
    asyncio.run(main())
