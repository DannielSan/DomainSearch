import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import models
from database import engine, get_db
from hunter import hunt_emails_on_web
from verifier import verify_email_realtime

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="DomainSearch Pro")

class CompanyRequest(BaseModel):
    domain: str

async def process_domain_scan(domain: str, db: Session):
    print(f"\n--- INICIANDO VARREDURA PARA {domain} ---")
    
    # 1. Garante empresa no banco
    company = db.query(models.Company).filter(models.Company.domain == domain).first()
    if not company:
        company = models.Company(domain=domain, name=domain)
        db.add(company)
        db.commit()
        db.refresh(company)

    # 2. Roda o Hunter (Crawler + Bing)
    leads_encontrados = await hunt_emails_on_web(domain)
    
    # 3. Processa Resultados
    for lead_data in leads_encontrados:
        email = lead_data["email"]
        
        # Evita duplicados no banco
        exists = db.query(models.Lead).filter(models.Lead.email == email).first()
        if exists: continue

        # Validação
        status_validacao = verify_email_realtime(email)
        confidence = 50
        should_save = False

        # Regras de Salvamento:
        # A. Achado no Site (Crawler) -> Salva com 100% de certeza
        if lead_data["role"] in ["Site Oficial", "Página Interna"]:
            should_save = True
            confidence = 100
            status_validacao = "valid" # Se estava no site, existe.

        # B. Vindo do LinkedIn (Bing)
        elif lead_data["linkedin"]:
            if status_validacao == "valid":
                should_save = True
                confidence = 95
            elif status_validacao == "risky":
                # Risky no LinkedIn geralmente é Catch-All, salvamos com alerta
                should_save = True
                confidence = 60
            # Se for 'invalid', descartamos pois a permutação estava errada

        # C. Genéricos (só se validar)
        elif status_validacao != "invalid":
            should_save = True
            confidence = 50

        if should_save:
            nome_parts = lead_data["name"].split(" ")
            first = nome_parts[0]
            last = " ".join(nome_parts[1:]) if len(nome_parts) > 1 else ""

            novo_lead = models.Lead(
                email=email,
                first_name=first,
                last_name=last,
                status=status_validacao,
                confidence_score=confidence,
                company_id=company.id,
                linkedin_url=lead_data["linkedin"],
                job_title=lead_data["role"]
            )
            db.add(novo_lead)
            print(f"   💾 SALVO: {lead_data['name']} ({email}) [{status_validacao}]")
            try:
                db.commit()
            except:
                db.rollback()

    print(f"--- FIM DA VARREDURA ---")

@app.post("/api/scan")
async def start_scan(request: CompanyRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    background_tasks.add_task(process_domain_scan, request.domain, db)
    return {"message": "Busca iniciada.", "domain": request.domain}

@app.get("/api/results/{domain}")
def get_results(domain: str, db: Session = Depends(get_db)):
    company = db.query(models.Company).filter(models.Company.domain == domain).first()
    if not company: return {"status": "Não iniciado", "leads": []}
    return {"status": "Encontrado", "leads": company.leads}

@app.get("/view/{domain}", response_class=HTMLResponse)
def view_results(domain: str, db: Session = Depends(get_db)):
    company = db.query(models.Company).filter(models.Company.domain == domain).first()
    if not company: return "<h1>Empresa não encontrada. Faça uma busca primeiro.</h1>"

    leads_html = ""
    for lead in company.leads:
        linkedin_link = f'<a href="{lead.linkedin_url}" target="_blank">LinkedIn</a>' if lead.linkedin_url else "-"
        leads_html += f"""
        <tr>
            <td>{lead.first_name} {lead.last_name}</td>
            <td>{lead.email}</td>
            <td>{lead.job_title}</td>
            <td>{linkedin_link}</td>
            <td>{lead.confidence_score}%</td>
        </tr>
        """
    
    html_content = f"""
    <html>
        <head>
            <title>Leads: {domain}</title>
            <style>
                body {{ font-family: sans-serif; padding: 20px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
                tr:nth-child(even) {{ background-color: #f9f9f9; }}
                h1 {{ color: #333; }}
                .btn {{ background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <h1>Leads Encontrados: {domain}</h1>
            <p><a href="#" onclick="window.close()" class="btn">Fechar</a></p>
            <table>
                <tr>
                    <th>Nome</th>
                    <th>Email</th>
                    <th>Cargo</th>
                    <th>LinkedIn</th>
                    <th>Confiança</th>
                </tr>
                {leads_html}
            </table>
        </body>
    </html>
    """
    return html_content

@app.get("/")
def home(): return {"status": "Online"}

if __name__ == "__main__":
    import uvicorn
    # reload=False é crucial no Windows
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)