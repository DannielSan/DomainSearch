import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Request, Response, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import datetime
import models
from database import engine, get_db
import auth
from hunter import hunt_emails_on_web
from verifier import verify_email_realtime

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="DomainSearch Pro")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CompanyRequest(BaseModel):
    domain: str

# Controle de processos em andamento para evitar falsos "Zero Leads" no Popup
active_scans = set()

@app.on_event("startup")
def create_initial_admin():
    db = next(get_db())
    admin_email = "dsbarrettoo@gmail.com"
    admin = db.query(models.User).filter(models.User.email == admin_email).first()
    if not admin:
        new_admin = models.User(
            email=admin_email,
            cpf="000.000.000-00",
            hashed_password=auth.get_password_hash("Open@2025"),
            role="admin"
        )
        db.add(new_admin)
        db.commit()
        print(f"[*] Admin user {admin_email} created securely.")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = None):
    token = request.cookies.get("session_token")
    if token:
        try:
            # Se for tentar entrar no login ja logado, joga pra home
            payload = auth.jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        except: pass
        
    error_html = f'<div style="background:#fee2e2; color:#b91c1c; padding:12px; border-radius:8px; margin-bottom:16px; font-size:14px; text-align:center;">{error}</div>' if error else ""
    
    return f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>Login - DomainSearch CRM</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Inter', sans-serif; background-color: #f8fafc; margin: 0; display: flex; height: 100vh; align-items: center; justify-content: center; }}
            .login-box {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); width: 100%; max-width: 400px; }}
            .logo {{ text-align: center; font-size: 24px; font-weight: 700; color: #4f46e5; margin-bottom: 8px; }}
            .subtitle {{ text-align: center; color: #64748b; font-size: 14px; margin-bottom: 32px; }}
            .form-group {{ margin-bottom: 20px; }}
            label {{ display: block; margin-bottom: 8px; font-weight: 500; color: #1e293b; font-size: 14px; }}
            input {{ width: 100%; padding: 12px; border: 1px solid #e2e8f0; border-radius: 8px; box-sizing: border-box; font-family: 'Inter'; transition: 0.2s; }}
            input:focus {{ border-color: #4f46e5; outline: none; box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1); }}
            button {{ width: 100%; padding: 12px; background: #4f46e5; color: white; border: none; border-radius: 8px; font-weight: 600; font-size: 16px; cursor: pointer; transition: 0.2s; }}
            button:hover {{ background: #4338ca; }}
        </style>
    </head>
    <body>
        <div class="login-box">
            <div class="logo">DomainSearch Pro</div>
            <div class="subtitle">Faça login para acessar o seu CRM.</div>
            {error_html}
            <form action="/login" method="POST">
                <div class="form-group">
                    <label>E-mail corporativo</label>
                    <input type="email" name="email" required placeholder="seu@email.com">
                </div>
                <div class="form-group">
                    <label>Senha</label>
                    <input type="password" name="password" required placeholder="••••••••">
                </div>
                <button type="submit">Entrar no Sistema</button>
            </form>
        </div>
    </body>
    </html>
    """

@app.post("/login")
def login_post(response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not auth.verify_password(password, user.hashed_password):
        return RedirectResponse(url="/login?error=Email+ou+senha+incorretos.", status_code=status.HTTP_302_FOUND)
        
    if not user.is_active:
        return RedirectResponse(url="/login?error=Sua+conta+foi+desativada.", status_code=status.HTTP_302_FOUND)
        
    # Generate Token
    access_token = auth.create_access_token(data={"sub": str(user.id), "role": user.role})
    
    # Send user to dashboard
    resp = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    resp.set_cookie(key="session_token", value=access_token, httponly=True, max_age=auth.ACCESS_TOKEN_EXPIRE_DAYS*24*60*60)
    return resp

@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    resp.delete_cookie("session_token")
    return resp

async def process_domain_scan(domain: str, db: Session, user_id: int):
    print(f"\n--- INICIANDO VARREDURA PARA {domain} ---")
    active_scans.add(f"{user_id}_{domain}") # Marca como em andamento
    
    try:
        # 1. Garante empresa no banco PRO usuario atual
        company = db.query(models.Company).filter(
            models.Company.domain == domain, 
            models.Company.user_id == user_id
        ).first()
        if not company:
            company = models.Company(domain=domain, name=domain, user_id=user_id)
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
                    user_id=user_id,
                    linkedin_url=lead["linkedin"],
                    job_title=lead["role"]
                )
                db.add(novo_lead)
                print(f"   💾 ENCONTRADO/PROCESSADO: {lead['name']} ({email}) [{status_validacao} | {confidence}%]")
                try:
                    db.commit()
                except Exception as e:
                    db.rollback()
                    print(f"Erro ao salvar lead: {e}")

    finally:
        active_scans.discard(f"{user_id}_{domain}")
        print(f"--- FIM DA VARREDURA ---")

@app.post("/api/scan")
async def start_scan(request: CompanyRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    background_tasks.add_task(process_domain_scan, request.domain, db, current_user.id)
    return {"message": "Busca iniciada.", "domain": request.domain}

@app.get("/api/results/{domain}")
def get_results(domain: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    is_scanning = f"{current_user.id}_{domain}" in active_scans
    company = db.query(models.Company).filter(
        models.Company.domain == domain,
        models.Company.user_id == current_user.id
    ).first()
    
    if not company: 
        return {"status": "Não iniciado", "is_scanning": is_scanning, "leads": []}
        
    return {"status": "Encontrado", "is_scanning": is_scanning, "leads": company.leads}

@app.post("/api/leads/{id}/save")
def save_lead_manually(id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    lead = db.query(models.Lead).filter(
        models.Lead.id == id,
        models.Lead.user_id == current_user.id
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    
    lead.is_saved = True
    lead.saved_at = datetime.datetime.utcnow()
    db.commit()
    return {"status": "success", "is_saved": True}

@app.get("/view/{domain}", response_class=HTMLResponse)
def view_results(domain: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    admin_btn = '<a href="/admin/users" class="menu-item"><i class="fas fa-users-cog"></i> Admin Painel</a>' if current_user.role == "admin" else ""
    company = db.query(models.Company).filter(
        models.Company.domain == domain,
        models.Company.user_id == current_user.id
    ).first()
    if not company: return "<h1>Empresa não encontrada ou você não possui acesso.</h1>"

    if not company.leads:
        # Estado Vazio (Nenhum e-mail encontrado)
        leads_rows = """
        <tr>
            <td colspan="4" style="text-align: center; color: #64748b; padding: 40px 0;">
                <i class="fas fa-search-minus" style="font-size: 24px; color: #cbd5e1; margin-bottom: 10px; display: block;"></i>
                Nenhum e-mail encontrado
            </td>
        </tr>
        """
    else:
        leads_rows = ""
        for lead in company.leads:
            linkedin_btn = f'<a href="{lead.linkedin_url}" target="_blank" class="linkedin-btn"><i class="fab fa-linkedin-in"></i></a>' if lead.linkedin_url else '<span class="no-link">-</span>'
            
            # Cor da Confiança - Estilo sutil
            conf_class = "conf-low"
            status_dot = '<span class="dot dot-red"></span>'
            if lead.status == "valid": 
                conf_class = "conf-high"
                status_dot = '<span class="dot dot-green"></span>'
            elif lead.status == "risky": 
                conf_class = "conf-med"
                status_dot = '<span class="dot dot-yellow"></span>'

            # Avatar Color Hash
            initials = lead.first_name[0].upper() if lead.first_name else "?"
            
            # Botão de Adicionar Manualmente
            if lead.is_saved:
                add_action_html = f'<span class="badge {conf_class}">Adicionado</span>'
            else:
                add_action_html = f'<button class="add-btn" onclick="saveLead({lead.id}, this)"><i class="fas fa-plus"></i> Adicionar</button>'
            
            leads_rows += f"""
            <tr>
                <td>
                    <div class="user-info">
                        <div class="avatar">{initials}</div>
                        <div>
                            <div class="name">{lead.first_name} {lead.last_name}</div>
                            <div class="role">{lead.job_title}</div>
                        </div>
                    </div>
                </td>
                <td>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        {status_dot}
                        <span class="email">{lead.email}</span>
                    </div>
                </td>
                <td>{linkedin_btn}</td>
                <td style="text-align: right;">{add_action_html}</td>
            </tr>
            """
    
    html_template = f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>Leads: {domain}</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
        <style>
            :root {{
                --primary: #6366f1;
                --bg-main: #f8fafc;
                --sidebar: #4f46e5;
                --text-main: #1e293b;
                --text-sec: #64748b;
                --border: #e2e8f0;
            }}
            body {{ 
                font-family: 'Inter', sans-serif; 
                background-color: var(--bg-main); 
                margin: 0; 
                padding: 0; 
                color: var(--text-main);
                display: flex;
                height: 100vh;
            }}
            
            /* Sidebar Baseada no Snov.io */
            .sidebar {{
                width: 250px;
                background-color: var(--sidebar);
                color: white;
                display: flex;
                flex-direction: column;
            }}
            .logo-area {{
                padding: 20px 24px;
                font-size: 20px;
                font-weight: 600;
                display: flex;
                align-items: center;
                gap: 10px;
                border-bottom: 1px solid rgba(255,255,255,0.1);
            }}
            .menu-item {{
                padding: 12px 24px;
                color: rgba(255,255,255,0.8);
                font-size: 14px;
                font-weight: 500;
                display: flex;
                align-items: center;
                gap: 12px;
                cursor: pointer;
                transition: all 0.2s;
                text-decoration: none;
            }}
            .menu-item:hover {{
                background: rgba(255,255,255,0.05);
                color: white;
            }}
            .menu-item.active {{
                background: rgba(255,255,255,0.1);
                border-left: 4px solid white;
                color: white;
            }}
            .menu-label {{
                padding: 16px 24px 8px 24px;
                font-size: 12px;
                color: rgba(255,255,255,0.5);
                text-transform: uppercase;
                letter-spacing: 0.05em;
                font-weight: 600;
            }}

            /* Área Principal */
            .main-content {{
                flex: 1;
                display: flex;
                flex-direction: column;
                overflow: hidden;
            }}
            
            /* Header Topo */
            .top-header {{
                height: 60px;
                background: white;
                border-bottom: 1px solid var(--border);
                display: flex;
                align-items: center;
                padding: 0 32px;
                font-size: 14px;
                color: var(--text-sec);
            }}

            /* Área da Tabela */
            .content-area {{
                padding: 32px;
                overflow-y: auto;
            }}
            
            .page-title {{
                font-size: 18px;
                font-weight: 600;
                color: var(--text-main);
                margin: 0 0 20px 0;
            }}

            .table-container {{ 
                background: white; 
                border-radius: 8px; 
                border: 1px solid var(--border);
                overflow: hidden; 
            }}
            
            table {{ width: 100%; border-collapse: collapse; }}
            th {{ 
                background: #f8fafc; 
                text-align: left; 
                padding: 14px 24px; 
                font-size: 11px; 
                color: var(--text-sec); 
                text-transform: uppercase; 
                letter-spacing: 0.05em; 
                font-weight: 600; 
                border-bottom: 1px solid var(--border); 
            }}
            td {{ 
                padding: 16px 24px; 
                border-bottom: 1px solid var(--border); 
                vertical-align: middle; 
            }}
            tr:last-child td {{ border-bottom: none; }}
            tr:hover {{ background-color: #f8fafc; cursor: default; }}

            /* Elementos da Tabela */
            .user-info {{ display: flex; align-items: center; gap: 12px; }}
            .avatar {{ 
                width: 32px; height: 32px; 
                background: #eef2ff; color: var(--primary); 
                border-radius: 50%; 
                display: flex; align-items: center; justify-content: center; 
                font-weight: 600; font-size: 13px; 
            }}
            .name {{ font-weight: 500; font-size: 13px; color: var(--primary); cursor: pointer; }}
            .role {{ font-size: 12px; color: var(--text-sec); margin-top: 2px; }}
            .email {{ color: var(--text-main); font-size: 13px; font-weight: 500; }}

            /* Botão LinkedIn e Status */
            .linkedin-btn {{ 
                color: #0077b5; 
                font-size: 16px; 
                text-decoration: none; 
                transition: opacity 0.2s; 
            }}
            .linkedin-btn:hover {{ opacity: 0.8; }}
            .no-link {{ color: #cbd5e1; font-size: 12px; }}

            .dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}
            .dot-green {{ background-color: #10b981; }}
            .dot-yellow {{ background-color: #f59e0b; }}
            .dot-red {{ background-color: #ef4444; }}

            /* Labels (Tags) e Botões */
            .badge {{ 
                padding: 4px 10px; 
                border-radius: 4px; 
                font-size: 11px; 
                font-weight: 500; 
                display: inline-block;
            }}
            .conf-high {{ background: #f1f5f9; color: var(--text-sec); border: 1px solid var(--border); }}
            .conf-med {{ background: #f1f5f9; color: var(--text-sec); border: 1px solid var(--border); }}
            .conf-low {{ background: #f1f5f9; color: var(--text-sec); border: 1px solid var(--border); }}

            .add-btn {{
                background: white;
                color: var(--primary);
                border: 1px solid var(--primary);
                padding: 4px 12px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s;
            }}
            .add-btn:hover {{ background: #eef2ff; }}
            .add-btn i {{ margin-right: 4px; }}

        </style>
    </head>
    <body>
        <div class="sidebar">
            <div class="logo-area">
                <i class="fas fa-satellite-dish"></i> DomainSearch
            </div>
            <div class="menu-label">MENU PRINCIPAL</div>
            <a href="/" class="menu-item">
                <i class="fas fa-home"></i> Início
            </a>
            <div class="menu-label">DADOS</div>
            <a href="/companies" class="menu-item active">
                <i class="far fa-user"></i> Clientes potenciais
            </a>
            <a href="/crm" class="menu-item">
                <i class="fas fa-users"></i> Seus Contatos (CRM)
            </a>
            {admin_btn}
            <a href="/logout" class="logout-btn"><i class="fas fa-sign-out-alt"></i> Sair</a>
        </div>

        <div class="main-content">
            <div class="top-header">
                <div><i class="fas fa-search"></i> Explorador / {domain}</div>
            </div>
            
            <div class="content-area">
                <h1 class="page-title">Lista de clientes potenciais</h1>
                
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Clientes Potenciais</th>
                                <th>E-mails</th>
                                <th>LinkedIn</th>
                                <th style="text-align: right;">Etiquetas / Ação</th>
                            </tr>
                        </thead>
                        <tbody>
                            {leads_rows}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <script>
            async function saveLead(id, btnElement) {{
                btnElement.disabled = true;
                btnElement.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Salvando...';
                
                try {{
                    const res = await fetch(`/api/leads/${{id}}/save`, {{ method: 'POST' }});
                    if (res.ok) {{
                        // Altera na marra parecendo a tag de "Adicionado" para fluidez 
                        const wrapper = document.createElement('span');
                        wrapper.className = 'badge conf-high';
                        wrapper.innerText = 'Adicionado';
                        btnElement.parentNode.replaceChild(wrapper, btnElement);
                    }}
                }} catch (e) {{
                    alert("Erro ao salvar.");
                    btnElement.disabled = false;
                    btnElement.innerHTML = '<i class="fas fa-plus"></i> Adicionar';
                }}
            }}
        </script>
    </body>
    </html>
    """
    return html_template

@app.get("/", response_class=HTMLResponse)
def home(current_user: models.User = Depends(auth.get_current_active_user)): 
    admin_btn = '<a href="/admin/users" class="menu-item"><i class="fas fa-users-cog"></i> Admin Painel</a>' if current_user.role == "admin" else ""
    return """
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>DomainSearch Home</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
        <style>
            :root {
                --primary: #6366f1;
                --bg-main: #f8fafc;
                --sidebar: #4f46e5;
                --text-main: #1e293b;
                --text-sec: #64748b;
                --border: #e2e8f0;
            }
            body { 
                font-family: 'Inter', sans-serif; 
                background-color: var(--bg-main); 
                margin: 0; 
                padding: 0; 
                color: var(--text-main);
                display: flex;
                height: 100vh;
            }
            .sidebar {
                width: 250px;
                background-color: var(--sidebar);
                color: white;
                display: flex;
                flex-direction: column;
            }
            .logo-area {
                padding: 20px 24px;
                font-size: 20px;
                font-weight: 600;
                display: flex;
                align-items: center;
                gap: 10px;
                border-bottom: 1px solid rgba(255,255,255,0.1);
            }
            .menu-item {
                padding: 12px 24px;
                color: rgba(255,255,255,0.8);
                font-size: 14px;
                font-weight: 500;
                display: flex;
                align-items: center;
                gap: 12px;
                cursor: pointer;
                transition: all 0.2s;
                text-decoration: none;
            }
            .menu-item:hover {
                background: rgba(255,255,255,0.05);
                color: white;
            }
            .menu-item.active {
                background: rgba(255,255,255,0.1);
                border-left: 4px solid white;
                color: white;
            }
            .logout-btn {
                margin-top: auto;
                padding: 16px 24px;
                color: #fca5a5;
                font-size: 14px;
                font-weight: 500;
                display: flex;
                align-items: center;
                gap: 12px;
                cursor: pointer;
                transition: all 0.2s;
                text-decoration: none;
                border-top: 1px solid rgba(255,255,255,0.1);
            }
            .logout-btn:hover {
                background: rgba(239,68,68,0.2);
                color: white;
            }
            .menu-label {
                padding: 16px 24px 8px 24px;
                font-size: 12px;
                color: rgba(255,255,255,0.5);
                text-transform: uppercase;
                letter-spacing: 0.05em;
                font-weight: 600;
            }
            .logout-btn {
                margin-top: auto;
                padding: 16px 24px;
                color: #fca5a5;
                font-size: 14px;
                font-weight: 500;
                display: flex;
                align-items: center;
                gap: 12px;
                cursor: pointer;
                transition: all 0.2s;
                text-decoration: none;
                border-top: 1px solid rgba(255,255,255,0.1);
            }
            .logout-btn:hover {
                background: rgba(239,68,68,0.2);
                color: white;
            }
            .main-content {
                flex: 1;
                display: flex;
                flex-direction: column;
                overflow-y: auto;
            }
            .top-header {
                height: 60px;
                background: white;
                border-bottom: 1px solid var(--border);
                display: flex;
                align-items: center;
                padding: 0 32px;
                font-size: 14px;
                color: var(--text-sec);
            }
            .hero-section {
                padding: 40px 32px;
                background: linear-gradient(180deg, white 0%, var(--bg-main) 100%);
                border-bottom: 1px solid var(--border);
            }
            .hero-title {
                font-size: 24px;
                font-weight: 700;
                color: #0f172a;
                margin: 0 0 8px 0;
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .hero-subtitle {
                color: var(--text-sec);
                margin: 0;
                font-size: 15px;
            }
            .cards-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                gap: 24px;
                padding: 32px;
            }
            .tool-card {
                background: white;
                border: 1px solid var(--border);
                border-radius: 12px;
                padding: 24px;
                cursor: pointer;
                transition: all 0.2s;
                position: relative;
                overflow: hidden;
            }
            .tool-card:hover {
                border-color: var(--primary);
                box-shadow: 0 4px 12px rgba(99, 102, 241, 0.1);
                transform: translateY(-2px);
            }
            .tool-icon {
                width: 48px;
                height: 48px;
                background: #eef2ff;
                color: var(--primary);
                border-radius: 12px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 20px;
                margin-bottom: 16px;
            }
            .tool-title {
                font-size: 16px;
                font-weight: 600;
                color: #1e293b;
                margin: 0 0 8px 0;
            }
            .tool-desc {
                font-size: 13px;
                color: var(--text-sec);
                line-height: 1.5;
                margin: 0;
            }
            
            /* Decorador das Bolinhas bg */
            .tool-card .bg-decorator {
                position: absolute;
                top: -20px;
                right: -20px;
                width: 100px;
                height: 100px;
                background: #f8fafc;
                border-radius: 50%;
                z-index: 0;
                transition: all 0.5s;
            }
            .tool-card:hover .bg-decorator {
                background: #eef2ff;
                transform: scale(1.5);
            }
            .tool-card > * { position: relative; z-index: 1; }
        </style>
    </head>
    <body>
        <div class="sidebar">
            <div class="logo-area">
                <i class="fas fa-satellite-dish"></i> DomainSearch
            </div>
            <div style="padding: 16px 24px 8px 24px; font-size: 12px; color: rgba(255,255,255,0.5); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;">
                MENU PRINCIPAL
            </div>
            <a href="/" style="text-decoration: none; padding: 12px 24px; background: rgba(255,255,255,0.1); border-left: 4px solid white; color: white; display: flex; align-items: center; gap: 12px; font-size: 14px; font-weight: 500; cursor: pointer;">
                <i class="fas fa-home"></i> Início
            </a>
            <div style="padding: 16px 24px 8px 24px; font-size: 12px; color: rgba(255,255,255,0.5); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;">
                DADOS
            </div>
            <a href="/companies" style="text-decoration: none; padding: 12px 24px; color: rgba(255,255,255,0.8); display: flex; align-items: center; gap: 12px; font-size: 14px; font-weight: 500; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.05)';" onmouseout="this.style.background='transparent';">
                <i class="far fa-user"></i> Clientes potenciais
            </a>
            <a href="/crm" style="text-decoration: none; padding: 12px 24px; color: rgba(255,255,255,0.8); display: flex; align-items: center; gap: 12px; font-size: 14px; font-weight: 500; cursor: pointer; transition: all 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.05)';" onmouseout="this.style.background='transparent';">
                <i class="fas fa-users"></i> Seus Contatos (CRM)
            </a>
            """ + admin_btn + """
            <a href="/logout" class="logout-btn"><i class="fas fa-sign-out-alt"></i> Sair</a>
        </div>

        <div class="main-content">
            <div class="top-header">
                <div><i class="fas fa-chart-line"></i> Dashboard / Início</div>
            </div>
            
            <div class="hero-section">
                <h1 class="hero-title"><i class="fas fa-rocket" style="color: var(--primary);"></i> Encontre clientes potenciais em qualquer lugar!</h1>
                <p class="hero-subtitle">Utilize nossas ferramentas de inteligência em vendas para prospectar os melhores leads.</p>
            </div>

            <div class="cards-grid">
                <!-- Card 1 -->
                <div class="tool-card" onclick="window.location.href='/companies'">
                    <div class="bg-decorator"></div>
                    <div class="tool-icon"><i class="fas fa-list-ul"></i></div>
                    <h3 class="tool-title">Ver minhas listas</h3>
                    <p class="tool-desc">Visualize e gerencie os clientes potenciais adicionados às listas para organizar seu CRM.</p>
                </div>
                
                <!-- Card 2 -->
                <div class="tool-card">
                    <div class="bg-decorator"></div>
                    <div class="tool-icon"><i class="fas fa-user-friends"></i></div>
                    <h3 class="tool-title">Encontrar mais pessoas</h3>
                    <p class="tool-desc">Encontre leads por nome, cargo, local, habilidades e muito mais no nosso motor inteligente.</p>
                </div>

                <!-- Card 3 -->
                <div class="tool-card">
                    <div class="bg-decorator"></div>
                    <div class="tool-icon"><i class="far fa-building"></i></div>
                    <h3 class="tool-title">Descobrindo empresas</h3>
                    <p class="tool-desc">Encontre empresas que se encaixem perfeitamente no seu Perfil de Cliente Ideal (ICP).</p>
                </div>

                <!-- Card 4 -->
                <div class="tool-card">
                    <div class="bg-decorator"></div>
                    <div class="tool-icon"><i class="fas fa-envelope-open-text"></i></div>
                    <h3 class="tool-title">Encontrar funcionários</h3>
                    <p class="tool-desc">Descubra todos os endereços de e-mail de um domínio específico navegando pela nossa extensão.</p>
                </div>

                <!-- Card 5 -->
                <div class="tool-card">
                    <div class="bg-decorator"></div>
                    <div class="tool-icon"><i class="fas fa-check-double"></i></div>
                    <h3 class="tool-title">Verificar contatos</h3>
                    <p class="tool-desc">Valide os e-mails dos clientes potenciais antes de contatá-los para reduzir bounces.</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

@app.get("/companies", response_class=HTMLResponse)
def view_companies(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    admin_btn = '<a href="/admin/users" class="menu-item"><i class="fas fa-users-cog"></i> Admin Painel</a>' if current_user.role == "admin" else ""
    companies = db.query(models.Company).filter(models.Company.user_id == current_user.id).all()
    
    # Monta a lista de cartões (uma para cada empresa)
    companies_html = ""
    for comp in companies:
        leads_count = len(comp.leads)
        companies_html += f"""
        <div class="tool-card" style="display:flex; justify-content:space-between; align-items:center; padding: 20px;" onclick="window.location.href='/view/{comp.domain}'">
            <div style="display:flex; align-items:center; gap: 16px;">
                <div class="tool-icon" style="margin-bottom: 0; width: 40px; height: 40px; font-size: 16px;"><i class="far fa-building"></i></div>
                <div>
                    <h3 class="tool-title" style="margin: 0 0 4px 0;">{comp.domain}</h3>
                    <p class="tool-desc">{leads_count} Leads encontrados</p>
                </div>
            </div>
            <div>
                <button style="background: var(--primary); color: white; border: none; padding: 8px 16px; border-radius: 8px; font-weight: 500; cursor: pointer; transition: 0.2s;" onmouseover="this.style.opacity='0.9'" onmouseout="this.style.opacity='1'">Ver Leads <i class="fas fa-arrow-right" style="margin-left:8px;"></i></button>
            </div>
        </div>
        """
        
    if not companies:
        companies_html = """
        <div style="text-align:center; padding: 60px 0; color: var(--text-sec);">
            <i class="fas fa-folder-open" style="font-size: 48px; opacity: 0.5; margin-bottom: 16px;"></i>
            <h3>Nenhuma empresa pesquisada ainda.</h3>
            <p>Utilize a extensão DomainSearch em um site para começar a gerar suas listas.</p>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>Minhas Listas - DomainSearch</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
        <style>
            :root {{
                --primary: #6366f1;
                --bg-main: #f8fafc;
                --sidebar: #4f46e5;
                --text-main: #1e293b;
                --text-sec: #64748b;
                --border: #e2e8f0;
            }}
            body {{ font-family: 'Inter', sans-serif; background-color: var(--bg-main); margin: 0; padding: 0; color: var(--text-main); display: flex; height: 100vh; }}
            .sidebar {{ width: 250px; background-color: var(--sidebar); color: white; display: flex; flex-direction: column; }}
            .logo-area {{ padding: 20px 24px; font-size: 20px; font-weight: 600; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid rgba(255,255,255,0.1); }}
            .menu-item {{ padding: 12px 24px; color: rgba(255,255,255,0.8); font-size: 14px; font-weight: 500; display: flex; align-items: center; gap: 12px; cursor: pointer; transition: all 0.2s; text-decoration: none; }}
            .menu-item:hover {{ background: rgba(255,255,255,0.05); color: white; }}
            .menu-item.active {{ background: rgba(255,255,255,0.1); border-left: 4px solid white; color: white; }}
            .menu-label {{ padding: 16px 24px 8px 24px; font-size: 12px; color: rgba(255,255,255,0.5); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }}
            .logout-btn {{ margin-top: auto; padding: 16px 24px; color: #fca5a5; font-size: 14px; font-weight: 500; display: flex; align-items: center; gap: 12px; cursor: pointer; transition: all 0.2s; text-decoration: none; border-top: 1px solid rgba(255,255,255,0.1); }}
            .logout-btn:hover {{ background: rgba(239,68,68,0.2); color: white; }}
            .main-content {{ flex: 1; display: flex; flex-direction: column; overflow-y: auto; }}
            .top-header {{ height: 60px; background: white; border-bottom: 1px solid var(--border); display: flex; align-items: center; padding: 0 32px; font-size: 14px; color: var(--text-sec); }}
            .page-header {{ padding: 32px; background: white; border-bottom: 1px solid var(--border); }}
            .page-title {{ font-size: 24px; font-weight: 700; margin: 0; color: #0f172a; }}
            .cards-list {{ padding: 32px; display: flex; flex-direction: column; gap: 16px; max-width: 900px; }}
            .tool-card {{ background: white; border: 1px solid var(--border); border-radius: 12px; cursor: pointer; transition: all 0.2s; }}
            .tool-card:hover {{ border-color: var(--primary); box-shadow: 0 4px 12px rgba(99, 102, 241, 0.1); transform: translateY(-2px); }}
            .tool-icon {{ background: #eef2ff; color: var(--primary); border-radius: 12px; display: flex; align-items: center; justify-content: center; }}
            .tool-title {{ font-size: 16px; font-weight: 600; color: #1e293b; }}
            .tool-desc {{ font-size: 13px; color: var(--text-sec); margin: 0; }}
        </style>
    </head>
    <body>
        <div class="sidebar">
            <div class="logo-area"><i class="fas fa-satellite-dish"></i> DomainSearch</div>
            <div class="menu-label">MENU PRINCIPAL</div>
            <a href="/" class="menu-item"><i class="fas fa-home"></i> Início</a>
            <div class="menu-label">DADOS</div>
            <a href="/companies" class="menu-item active"><i class="far fa-user"></i> Clientes potenciais</a>
            <a href="/crm" class="menu-item"><i class="fas fa-users"></i> Seus Contatos (CRM)</a>
            {admin_btn}
            <a href="/logout" class="logout-btn"><i class="fas fa-sign-out-alt"></i> Sair</a>
        </div>
        <div class="main-content">
            <div class="top-header">
                <div><i class="fas fa-list-ul"></i> Clientes Potenciais / Minhas Listas</div>
            </div>
            <div class="page-header">
                <h1 class="page-title">Minhas Listas</h1>
                <p style="color: var(--text-sec); margin: 8px 0 0 0;">Acesse e gerencie todos os domínios mapeados.</p>
            </div>
            <div class="cards-list">
                {companies_html}
            </div>
        </div>
    </body>
    </html>
    """

@app.get("/crm", response_class=HTMLResponse)
def view_crm(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    admin_btn = '<a href="/admin/users" class="menu-item"><i class="fas fa-users-cog"></i> Admin Painel</a>' if current_user.role == "admin" else ""
    # Busca apenas leads salvos manualmente pro usuario logado
    saved_leads = db.query(models.Lead).filter(
        models.Lead.is_saved == True,
        models.Lead.user_id == current_user.id
    ).order_by(models.Lead.saved_at.desc()).all()
    
    leads_rows = ""
    for lead in saved_leads:
        company_name = lead.company.domain if lead.company else "Desconhecido"
        saved_date = lead.saved_at.strftime("%d/%m/%Y") if lead.saved_at else "Anteriormente"
        raw_date = lead.saved_at.strftime("%Y-%m-%d") if lead.saved_at else "2000-01-01"
        
        initials = (lead.first_name[0] if lead.first_name else "C").upper()
        avatar_bg = "#eef2ff"
        avatar_color = "#6366f1"
        
        linkedin_btn = f'<a href="{lead.linkedin_url}" target="_blank" title="Abrir LinkedIn" style="color:#0077b5; font-size:18px;"><i class="fab fa-linkedin"></i></a>' if lead.linkedin_url else "-"
        
        # O atributo data-* será usado no Javascript para filtrar visualmente sem recarregar
        full_name = f"{lead.first_name} {lead.last_name or ''}".lower()
        company_lower = company_name.lower()
        
        leads_rows += f"""
        <tr class="lead-row" data-name="{full_name}" data-email="{lead.email.lower()}" data-company="{company_lower}" data-date="{raw_date}">
            <td>
                <div style="font-weight: 500; color: #334155;"><i class="far fa-building" style="margin-right:6px; color:var(--text-sec)"></i>{company_name}</div>
            </td>
            <td>
                <div class="user-info">
                    <div class="avatar" style="background:{avatar_bg}; color:{avatar_color}; width:32px; height:32px; display:flex; align-items:center; justify-content:center; border-radius:50%; font-weight:600; font-size:14px; margin-right:12px;">{initials}</div>
                    <div>
                        <div class="name" style="font-weight:600; color:#1e293b;">{lead.first_name} {lead.last_name}</div>
                        <div class="role" style="font-size:12px; color:var(--text-sec);">{lead.job_title}</div>
                    </div>
                </div>
            </td>
            <td>
                <span class="email" style="font-weight:500; color:#475569;">{lead.email}</span>
            </td>
            <td>{linkedin_btn}</td>
            <td style="color:var(--text-sec); font-size:13px;"><i class="far fa-clock" style="margin-right:4px;"></i>{saved_date}</td>
        </tr>
        """
        
    if not saved_leads:
        leads_rows = """
        <tr>
            <td colspan="5" style="text-align:center; padding: 40px; color: var(--text-sec);">
                <i class="fas fa-users-slash" style="font-size: 32px; margin-bottom: 16px; opacity:0.5;"></i><br>
                Nenhum lead salvo no CRM ainda.
            </td>
        </tr>
        """
        
    # Obtém lista única de empresas que possuem leads salvos para o Dropdown
    companies_with_leads = set([l.company.domain for l in saved_leads if l.company])
    options_html = '<option value="all">Todas as Empresas</option>'
    for c in sorted(companies_with_leads):
        options_html += f'<option value="{c.lower()}">{c}</option>'

    return f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>Seus Contatos - CRM</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
        <style>
            :root {{
                --primary: #6366f1;
                --bg-main: #f8fafc;
                --sidebar: #4f46e5;
                --text-main: #1e293b;
                --text-sec: #64748b;
                --border: #e2e8f0;
            }}
            body {{ font-family: 'Inter', sans-serif; background-color: var(--bg-main); margin: 0; padding: 0; color: var(--text-main); display: flex; height: 100vh; overflow: hidden;}}
            
            /* Sidebar */
            .sidebar {{ width: 250px; background-color: var(--sidebar); color: white; display: flex; flex-direction: column; }}
            .logo-area {{ padding: 20px 24px; font-size: 20px; font-weight: 600; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid rgba(255,255,255,0.1); }}
            .menu-item {{ padding: 12px 24px; color: rgba(255,255,255,0.8); font-size: 14px; font-weight: 500; display: flex; align-items: center; gap: 12px; cursor: pointer; transition: all 0.2s; text-decoration: none; }}
            .menu-item:hover {{ background: rgba(255,255,255,0.05); color: white; }}
            .menu-item.active {{ background: rgba(255,255,255,0.1); border-left: 4px solid white; color: white; }}
            .menu-label {{ padding: 16px 24px 8px 24px; font-size: 12px; color: rgba(255,255,255,0.5); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }}
            .logout-btn {{ margin-top: auto; padding: 16px 24px; color: #fca5a5; font-size: 14px; font-weight: 500; display: flex; align-items: center; gap: 12px; cursor: pointer; transition: all 0.2s; text-decoration: none; border-top: 1px solid rgba(255,255,255,0.1); }}
            .logout-btn:hover {{ background: rgba(239,68,68,0.2); color: white; }}
            
            /* Main */
            .main-content {{ flex: 1; display: flex; flex-direction: column; overflow-y: auto; background-color: #f1f5f9; }}
            .top-header {{ height: 60px; min-height: 60px; background: white; border-bottom: 1px solid var(--border); display: flex; align-items: center; padding: 0 32px; font-size: 14px; color: var(--text-sec); }}
            
            /* CRM Hub */
            .crm-container {{ padding: 32px; max-width: 1200px; width: 100%; box-sizing: border-box; margin: 0 auto; }}
            .crm-header {{ display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 24px; }}
            .crm-title {{ font-size: 24px; font-weight: 700; margin: 0 0 8px 0; color: #0f172a; }}
            .crm-subtitle {{ color: var(--text-sec); margin: 0; font-size: 14px; }}
            
            /* Filters */
            .filters-bar {{ display: flex; gap: 16px; background: white; padding: 16px; border-radius: 12px; border: 1px solid var(--border); margin-bottom: 24px; align-items: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
            .filter-input {{ padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px; flex: 1; font-family: 'Inter'; font-size: 14px; outline: none; transition: 0.2s; }}
            .filter-input:focus {{ border-color: var(--primary); box-shadow: 0 0 0 3px rgba(99,102,241,0.1); }}
            .filter-select {{ padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px; width: 200px; font-family: 'Inter'; font-size: 14px; background: white; outline:none; }}
            .filter-date {{ padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px; width: 150px; font-family: 'Inter'; font-size: 14px; outline:none; color: var(--text-main); }}
            
            /* Table */
            .table-container {{ background: white; border-radius: 12px; border: 1px solid var(--border); overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
            table {{ width: 100%; border-collapse: collapse; text-align: left; }}
            th {{ font-size: 11px; text-transform: uppercase; color: var(--text-sec); font-weight: 600; padding: 16px 24px; border-bottom: 1px solid var(--border); background: #f8fafc; letter-spacing: 0.05em; }}
            td {{ padding: 16px 24px; border-bottom: 1px solid var(--border); font-size: 14px; }}
            tr:hover {{ background-color: #f8fafc; }}
            .user-info {{ display: flex; align-items: center; }}
            
        </style>
    </head>
    <body>
        <div class="sidebar">
            <div class="logo-area"><i class="fas fa-satellite-dish"></i> DomainSearch</div>
            <div class="menu-label">MENU PRINCIPAL</div>
            <a href="/" class="menu-item"><i class="fas fa-home"></i> Início</a>
            <div class="menu-label">DADOS</div>
            <a href="/companies" class="menu-item"><i class="far fa-user"></i> Clientes potenciais</a>
            <a href="/crm" class="menu-item active"><i class="fas fa-users"></i> Seus Contatos (CRM)</a>
            {admin_btn}
            <a href="/logout" class="logout-btn"><i class="fas fa-sign-out-alt"></i> Sair</a>
        </div>
        
        <div class="main-content">
            <div class="top-header">
                <div><i class="fas fa-users"></i> Menu / Seus Contatos (CRM)</div>
            </div>
            
            <div class="crm-container">
                <div class="crm-header">
                    <div>
                        <h1 class="crm-title">Seus Contatos Reservados</h1>
                        <p class="crm-subtitle">Visualize todos os leads que você adicionou manualmente através das listas.</p>
                    </div>
                    <div style="background: #eef2ff; color: var(--primary); padding: 8px 16px; border-radius: 20px; font-weight: 600; font-size: 14px;">
                        {len(saved_leads)} Leads Salvos
                    </div>
                </div>
                
                <div class="filters-bar">
                    <i class="fas fa-search" style="color:var(--text-sec); margin-left: 8px;"></i>
                    <input type="text" id="searchInput" class="filter-input" placeholder="Buscar por nome ou e-mail..." onkeyup="filterLeads()">
                    
                    <select id="companyFilter" class="filter-select" onchange="filterLeads()">
                        {options_html}
                    </select>
                    
                    <input type="date" id="dateFilter" class="filter-date" onchange="filterLeads()" title="Filtrar por Data de Adição">
                    
                    <button onclick="clearFilters()" style="padding: 10px 16px; border: 1px solid var(--border); background: white; border-radius: 8px; cursor: pointer; color: var(--text-main); font-weight: 500;"><i class="fas fa-times" style="margin-right: 6px;"></i> Limpar</button>
                </div>
                
                <div class="table-container">
                    <table id="leadsTable">
                        <thead>
                            <tr>
                                <th>Origem (Empresa)</th>
                                <th>Lead</th>
                                <th>E-mail</th>
                                <th>LinkedIn</th>
                                <th>Adicionado em</th>
                            </tr>
                        </thead>
                        <tbody>
                            {leads_rows}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <script>
            function filterLeads() {{
                const search = document.getElementById('searchInput').value.toLowerCase();
                const company = document.getElementById('companyFilter').value;
                const date = document.getElementById('dateFilter').value; // 'YYYY-MM-DD'
                
                const rows = document.querySelectorAll('.lead-row');
                
                rows.forEach(row => {{
                    const rName = row.getAttribute('data-name');
                    const rEmail = row.getAttribute('data-email');
                    const rCompany = row.getAttribute('data-company');
                    const rDate = row.getAttribute('data-date');
                    
                    // Condições
                    const matchSearch = rName.includes(search) || rEmail.includes(search);
                    const matchCompany = company === 'all' || rCompany === company;
                    const matchDate = date === '' || rDate === date;
                    
                    if (matchSearch && matchCompany && matchDate) {{
                        row.style.display = '';
                    }} else {{
                        row.style.display = 'none';
                    }}
                }});
            }}
            
            function clearFilters() {{
                document.getElementById('searchInput').value = '';
                document.getElementById('companyFilter').value = 'all';
                document.getElementById('dateFilter').value = '';
                filterLeads();
            }}
        </script>
    </body>
    </html>
    """

@app.get("/admin/users", response_class=HTMLResponse)
def view_admin_users(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user), error: str = None, success: str = None):
    users = db.query(models.User).order_by(models.User.id.desc()).all()
    
    users_rows = ""
    for u in users:
        role_label = '<span style="background:#eef2ff; color:var(--primary); padding:4px 8px; border-radius:4px; font-size:12px; font-weight:600;">Admin</span>' if u.role == 'admin' else '<span style="background:#f1f5f9; color:var(--text-sec); padding:4px 8px; border-radius:4px; font-size:12px; font-weight:600;">Funcionário</span>'
        status_label = '<span style="color:#10b981; font-weight:600;">Ativo</span>' if u.is_active else '<span style="color:#ef4444; font-weight:600;">Inativo</span>'
        
        users_rows += f"""
        <tr>
            <td>{u.id}</td>
            <td style="font-weight:600;">{u.email}</td>
            <td>{u.cpf}</td>
            <td>{role_label}</td>
            <td>{status_label}</td>
            <td>{u.created_at.strftime("%d/%m/%Y")}</td>
        </tr>
        """
        
    error_html = f'<div style="background:#fee2e2; color:#b91c1c; padding:12px; border-radius:8px; margin-bottom:16px;">{error}</div>' if error else ""
    success_html = f'<div style="background:#dcfce3; color:#15803d; padding:12px; border-radius:8px; margin-bottom:16px;">{success}</div>' if success else ""

    return f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>Painel Admin - DomainSearch</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
        <style>
            :root {{
                --primary: #6366f1;
                --bg-main: #f8fafc;
                --sidebar: #4f46e5;
                --text-main: #1e293b;
                --text-sec: #64748b;
                --border: #e2e8f0;
            }}
            body {{ font-family: 'Inter', sans-serif; background-color: var(--bg-main); margin: 0; padding: 0; color: var(--text-main); display: flex; height: 100vh; }}
            .sidebar {{ width: 250px; background-color: var(--sidebar); color: white; display: flex; flex-direction: column; }}
            .logo-area {{ padding: 20px 24px; font-size: 20px; font-weight: 600; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid rgba(255,255,255,0.1); }}
            .menu-item {{ padding: 12px 24px; color: rgba(255,255,255,0.8); font-size: 14px; font-weight: 500; display: flex; align-items: center; gap: 12px; cursor: pointer; transition: all 0.2s; text-decoration: none; }}
            .menu-item:hover {{ background: rgba(255,255,255,0.05); color: white; }}
            .menu-item.active {{ background: rgba(255,255,255,0.1); border-left: 4px solid white; color: white; }}
            .menu-label {{ padding: 16px 24px 8px 24px; font-size: 12px; color: rgba(255,255,255,0.5); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }}
            .main-content {{ flex: 1; display: flex; flex-direction: column; overflow-y: auto; background-color: #f1f5f9; }}
            .top-header {{ height: 60px; min-height: 60px; background: white; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; padding: 0 32px; font-size: 14px; color: var(--text-sec); }}
            
            .admin-container {{ padding: 32px; max-width: 1200px; width: 100%; box-sizing: border-box; margin: 0 auto; }}
            
            .box {{ background: white; border-radius: 12px; border: 1px solid var(--border); padding: 24px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
            
            h2 {{ margin-top: 0; color: #0f172a; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; font-size: 20px; }}
            
            /* Formulario */
            .form-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }}
            .form-group {{ margin-bottom: 16px; }}
            label {{ display: block; margin-bottom: 8px; font-weight: 500; font-size: 13px; color: #334155; }}
            input, select {{ width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; font-family: 'Inter'; font-size: 14px; box-sizing: border-box; outline: none; }}
            input:focus, select:focus {{ border-color: var(--primary); box-shadow: 0 0 0 3px rgba(99,102,241,0.1); }}
            button {{ background: var(--primary); color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; transition: 0.2s; }}
            button:hover {{ background: #4338ca; }}
            
            /* Tabela */
            table {{ width: 100%; border-collapse: collapse; text-align: left; }}
            th {{ font-size: 12px; text-transform: uppercase; color: var(--text-sec); font-weight: 600; padding: 12px 16px; border-bottom: 1px solid var(--border); background: #f8fafc; }}
            td {{ padding: 16px; border-bottom: 1px solid var(--border); font-size: 14px; }}
            tr:hover {{ background-color: #f8fafc; }}
            
        </style>
    </head>
    <body>
        <div class="sidebar">
            <div class="logo-area"><i class="fas fa-satellite-dish"></i> DomainSearch</div>
            <div class="menu-label">MENU PRINCIPAL</div>
            <a href="/" class="menu-item"><i class="fas fa-home"></i> Início</a>
            <div class="menu-label">DADOS</div>
            <a href="/companies" class="menu-item"><i class="far fa-user"></i> Clientes potenciais</a>
            <a href="/crm" class="menu-item"><i class="fas fa-users"></i> Seus Contatos (CRM)</a>
            <a href="/admin/users" class="menu-item active"><i class="fas fa-users-cog"></i> Admin Painel</a>
        </div>
        
        <div class="main-content">
            <div class="top-header">
                <div><i class="fas fa-shield-alt"></i> Administração / Controle de Equipe</div>
                <div><a href="/logout" style="color: #ef4444; font-weight: 500; text-decoration: none;"><i class="fas fa-sign-out-alt"></i> Sair</a></div>
            </div>
            
            <div class="admin-container">
                {error_html}
                {success_html}
                
                <div class="box">
                    <h2><i class="fas fa-user-plus" style="color:var(--primary)"></i> Adicionar Novo Usuário</h2>
                    <form action="/admin/users/create" method="POST">
                        <div class="form-grid">
                            <div class="form-group">
                                <label>E-mail corporativo</label>
                                <input type="email" name="email" required placeholder="funcionario@suaempresa.com">
                            </div>
                            <div class="form-group">
                                <label>CPF (Acesso único)</label>
                                <input type="text" name="cpf" required placeholder="000.000.000-00">
                            </div>
                            <div class="form-group">
                                <label>Senha inicial</label>
                                <input type="password" name="password" required placeholder="••••••••">
                            </div>
                            <div class="form-group">
                                <label>Nível de Acesso</label>
                                <select name="role">
                                    <option value="employee">Funcionário (Apenas usar CRM)</option>
                                    <option value="admin">Administrador (Master)</option>
                                </select>
                            </div>
                        </div>
                        <button type="submit"><i class="fas fa-check"></i> Criar Conta</button>
                    </form>
                </div>
                
                <div class="box" style="padding: 0; overflow: hidden;">
                    <div style="padding: 24px 24px 16px 24px;">
                        <h2><i class="fas fa-list" style="color:var(--text-sec)"></i> Equipe Cadastrada</h2>
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>E-mail</th>
                                <th>CPF</th>
                                <th>Nível</th>
                                <th>Status</th>
                                <th>Data Adesão</th>
                            </tr>
                        </thead>
                        <tbody>
                            {users_rows}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

@app.post("/admin/users/create")
def create_admin_user(
    email: str = Form(...), 
    cpf: str = Form(...), 
    password: str = Form(...), 
    role: str = Form(...), 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(auth.get_current_admin_user)
):
    # Verifica duplicidade
    exists = db.query(models.User).filter((models.User.email == email) | (models.User.cpf == cpf)).first()
    if exists:
        return RedirectResponse(url="/admin/users?error=Email+ou+CPF+já+cadastrado.", status_code=status.HTTP_302_FOUND)
        
    new_user = models.User(
        email=email,
        cpf=cpf,
        hashed_password=auth.get_password_hash(password),
        role=role
    )
    db.add(new_user)
    db.commit()
    
    return RedirectResponse(url="/admin/users?success=Usuário+criado+com+sucesso!", status_code=status.HTTP_302_FOUND)

if __name__ == "__main__":
    import uvicorn
    # reload=False é crucial no Windows
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)