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
    for lead in leads_encontrados:
        email = lead["email"]
        
        # Evita duplicados no banco
        exists = db.query(models.Lead).filter(models.Lead.email == email).first()
        if exists: continue

        # Validação
        status_validacao = verify_email_realtime(email)
        confidence = 50
        should_save = False

        # --- NOVA LÓGICA DE PONTUAÇÃO (SMART SCORING) ---
        
        # A. Achado no Site (Crawler) -> Ouro (100%)
        if lead["role"] in ["Site Oficial", "Página Interna"]:
            should_save = True
            confidence = 100
            status_validacao = "valid"

        # B. Vindo do LinkedIn (Bing/Google) -> Prata (High Confidence)
        elif lead["linkedin"]:
            # Se tem LinkedIn e Cargo, é uma pessoa real.
            # Mesmo que o e-mail seja 'risky' (Catch-All), a existência da pessoa é garantida.
            should_save = True
            if status_validacao == "valid":
                confidence = 98
            elif status_validacao == "risky":
                confidence = 80 # Catch-All mas com perfil real = Alta chance
            else:
                confidence = 40 # Inválido, mas salvamos como "Baixa" por ter LinkedIn

        # C. Genéricos (só se validar)
        elif status_validacao != "invalid":
            should_save = True
            confidence = 50

        if should_save:
            nome_parts = lead["name"].split(" ")
            first = nome_parts[0]
            last = " ".join(nome_parts[1:]) if len(nome_parts) > 1 else ""

            novo_lead = models.Lead(
                email=email,
                first_name=first,
                last_name=last,
                status=status_validacao,
                confidence_score=confidence,
                company_id=company.id,
                linkedin_url=lead["linkedin"],
                job_title=lead["role"]
            )
            db.add(novo_lead)
            print(f"   💾 SALVO: {lead['name']} ({email}) [{status_validacao} | {confidence}%]")
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

    leads_rows = ""
    for lead in company.leads:
        linkedin_btn = f'<a href="{lead.linkedin_url}" target="_blank" class="linkedin-btn">LinkedIn</a>' if lead.linkedin_url else '<span class="no-link">-</span>'
        
        # Cor da Confiança
        conf_class = "conf-low"
        if lead.confidence_score >= 90: conf_class = "conf-high"
        elif lead.confidence_score >= 70: conf_class = "conf-med"

        leads_rows += f"""
        <tr>
            <td>
                <div class="user-info">
                    <div class="avatar">{lead.first_name[0]}</div>
                    <div>
                        <div class="name">{lead.first_name} {lead.last_name}</div>
                        <div class="role">{lead.job_title}</div>
                    </div>
                </div>
            </td>
            <td><span class="email">{lead.email}</span></td>
            <td>{linkedin_btn}</td>
            <td><span class="badge {conf_class}">{lead.confidence_score}%</span></td>
        </tr>
        """
    
    html_template = f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>Leads: {domain}</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Inter', sans-serif; background-color: #f3f4f6; margin: 0; padding: 40px; color: #1f2937; }}
            .container {{ max-width: 1000px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); overflow: hidden; }}
            
            header {{ padding: 24px 32px; border-bottom: 1px solid #e5e7eb; display: flex; justify-content: space-between; align-items: center; background: #fff; }}
            h1 {{ margin: 0; font-size: 20px; font-weight: 600; color: #111827; }}
            .domain-tag {{ background: #e0e7ff; color: #4338ca; padding: 4px 12px; border-radius: 99px; font-size: 14px; margin-left: 10px; }}
            
            table {{ width: 100%; border-collapse: collapse; }}
            th {{ background: #f9fafb; text-align: left; padding: 12px 32px; font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; border-bottom: 1px solid #e5e7eb; }}
            td {{ padding: 16px 32px; border-bottom: 1px solid #e5e7eb; vertical-align: middle; }}
            tr:last-child td {{ border-bottom: none; }}
            tr:hover {{ background-color: #f9fafb; }}

            .user-info {{ display: flex; align-items: center; gap: 12px; }}
            .avatar {{ width: 36px; height: 36px; background: #dbeafe; color: #1e40af; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 14px; text-transform: uppercase; }}
            .name {{ font-weight: 500; color: #111827; font-size: 14px; }}
            .role {{ font-size: 12px; color: #6b7280; margin-top: 2px; }}

            .email {{ color: #4b5563; font-size: 14px; font-family: monospace; }}

            .linkedin-btn {{ display: inline-flex; align-items: center; background: #0077b5; color: white; padding: 6px 12px; border-radius: 6px; text-decoration: none; font-size: 12px; font-weight: 500; transition: background 0.2s; }}
            .linkedin-btn:hover {{ background: #005a8d; }}
            .no-link {{ color: #9ca3af; font-size: 12px; }}

            .badge {{ padding: 4px 10px; border-radius: 99px; font-size: 12px; font-weight: 600; }}
            .conf-high {{ background: #dcfce7; color: #166534; }}
            .conf-med {{ background: #fef9c3; color: #854d0e; }}
            .conf-low {{ background: #fee2e2; color: #991b1b; }}

            .actions {{ margin-top: 0; }}
            .close-btn {{ background: white; border: 1px solid #d1d5db; color: #374151; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 500; transition: all 0.2s; text-decoration: none; }}
            .close-btn:hover {{ background: #f3f4f6; border-color: #9ca3af; }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <div style="display:flex; align-items:center;">
                    <h1>Resultados da Busca</h1>
                    <span class="domain-tag">{domain}</span>
                </div>
                <div class="actions">
                    <a href="#" onclick="window.close()" class="close-btn">Fechar Aba</a>
                </div>
            </header>
            <table>
                <thead>
                    <tr>
                        <th>Profissional</th>
                        <th>Email Corporativo</th>
                        <th>LinkedIn</th>
                        <th>Confiança</th>
                    </tr>
                </thead>
                <tbody>
                    {leads_rows}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    return html_template

@app.get("/")
def home(): return {"status": "Online"}

if __name__ == "__main__":
    import uvicorn
    # reload=False é crucial no Windows
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)