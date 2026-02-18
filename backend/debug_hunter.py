import asyncio
from hunter import hunt_emails_on_web

async def debug_hunt():
    domain = "opentreinamentos.com.br"
    print(f"🔬 DEBUG: Iniciando caçada para {domain}...")
    
    # Run the hunter and print detailed steps (hunter has print statements)
    results = await hunt_emails_on_web(domain)
    
    print("\n📊 RESULTADOS FINAIS:")
    for res in results:
        print(f" - {res['name']} ({res['email']}) [Role: {res['role']}] [LinkedIn: {res['linkedin']}]")

if __name__ == "__main__":
    asyncio.run(debug_hunt())
