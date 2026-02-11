import sys
import asyncio

# --- CORREÇÃO OBRIGATÓRIA PARA WINDOWS ---
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
# -----------------------------------------

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import models
from database import engine, get_db

from hunter import hunt_emails_on_web
from verifier import verify_email_realtime

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="DomainSearch API - Robust Mode")

class CompanyRequest(BaseModel):
    domain: str

async def process_domain_scan(domain: str, db: Session):
    print(f"Iniciando varredura em: {domain}")
    
    company = db.query(models.Company).filter(models.Company.domain == domain).first()
    if not company:
        company = models.Company(domain=domain, name=domain)
        db.add(company)
        db.commit()
        db.refresh(company)

    # Chama o Hunter
    leads_encontrados = await hunt_emails_on_web(domain)
    print(f"Leads brutos encontrados: {len(leads_encontrados)}")

    for lead_data in leads_encontrados:
        email = lead_data["email"]
        exists = db.query(models.Lead).filter(models.Lead.email == email).first()
        
        if not exists:
            # Tenta validar
            status_validacao = verify_email_realtime(email)
            
            # REGRA DE OURO:
            # 1. Se tem LinkedIn, salva SEMPRE (mesmo se der invalid/risky).
            # 2. Se não tem LinkedIn (genérico), só salva se NÃO for invalid.
            should_save = False
            
            if lead_data["linkedin"]: 
                should_save = True
                # Marca como risky se a validação técnica falhou, mas sabemos que a pessoa existe
                if status_validacao == "invalid":
                    status_validacao = "risky"
            elif status_validacao != "invalid":
                should_save = True

            if should_save:
                # Formatação do nome
                nome_parts = lead_data["name"].split(" ")
                first = nome_parts[0]
                last = " ".join(nome_parts[1:]) if len(nome_parts) > 1 else ""

                novo_lead = models.Lead(
                    email=email,
                    first_name=first,
                    last_name=last,
                    status=status_validacao,
                    confidence_score=90 if lead_data["linkedin"] else 50,
                    company_id=company.id,
                    linkedin_url=lead_data["linkedin"],
                    job_title=lead_data["role"]
                )
                db.add(novo_lead)
                print(f"💾 Salvo no Banco: {lead_data['name']}")
    
    db.commit()
    print(f"Varredura finalizada para {domain}")

@app.post("/api/scan")
async def start_scan(request: CompanyRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    background_tasks.add_task(process_domain_scan, request.domain, db)
    return {"message": "Busca iniciada.", "domain": request.domain}

@app.get("/api/results/{domain}")
def get_results(domain: str, db: Session = Depends(get_db)):
    company = db.query(models.Company).filter(models.Company.domain == domain).first()
    if not company:
        return {"status": "Não iniciado", "leads": []}
    return {"status": "Encontrado", "leads": company.leads}

@app.get("/")
def home():
    return {"status": "Online"}

if __name__ == "__main__":
    import uvicorn
    # reload=False é crucial no Windows
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)