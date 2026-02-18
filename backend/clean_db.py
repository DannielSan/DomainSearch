import sys
import asyncio
from sqlalchemy.orm import Session
from database import SessionLocal, engine
import models

# Force Windows event loop policy
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

BLACKLIST_TERMS = [
    "na.hora", "nas.horas", "na.semana", "no.mes", "no.ano", 
    "em.portugues", "videos", "pesquisar", "resultados", "modo", 
    "letra", "google", "bing", "yahoo", "duckduckgo", "search",
    "mapas", "shopping", "imagens", "noticias", "livros", "voos", "financas"
]

def clean_database():
    db = SessionLocal()
    print("--- INICIANDO LIMPEZA DO BANCO DE DADOS ---")
    
    deleted_count = 0
    leads = db.query(models.Lead).all()
    
    for lead in leads:
        should_delete = False
        
        # Check email
        if any(term in lead.email.lower() for term in BLACKLIST_TERMS):
            should_delete = True
            
        # Check name (optional, but good for "Vídeos curtos")
        if lead.first_name and any(term in lead.first_name.lower() for term in BLACKLIST_TERMS):
            should_delete = True
            
        if should_delete:
            print(f"❌ Removendo Lead Inválido: {lead.first_name} ({lead.email})")
            db.delete(lead)
            deleted_count += 1
            
    try:
        db.commit()
        print(f"\n✅ Limpeza Concluída! Total removidos: {deleted_count}")
    except Exception as e:
        print(f"⚠️ Erro ao commitar: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    clean_database()
