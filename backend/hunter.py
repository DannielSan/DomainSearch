from playwright.async_api import async_playwright
import re
import urllib.parse
import unicodedata
import asyncio
from typing import List, Dict, Set

# --- UTILITÁRIOS ---
def remove_accents(input_str):
    if not input_str: return ""
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

BLACKLIST_TERMS = [
    "na.hora", "nas.horas", "na.semana", "no.mes", "no.ano", 
    "em.portugues", "videos", "pesquisar", "resultados", "modo", 
    "letra", "google", "bing", "yahoo", "duckduckgo", "search",
    "mapas", "shopping", "imagens", "noticias", "livros", "voos", "financas"
]

def extract_emails_from_text(text: str, domain: str) -> Set[str]:
    """Regex para extrair e-mails de um texto cru"""
    if not text: return set()
    
    # Regex melhorado para evitar pontos finais no email (ex: email@dominio.com.)
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    matches = re.findall(email_pattern, text)
    valid_emails = set()
    
    for email in matches:
        # Remove ponto final se houver (comum em finais de frase)
        email = email.rstrip('.')
        
        if domain in email.lower():
            if not email.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.css', '.js', '.webp', '.svg', '.woff')):
                # Filter Blacklist
                if not any(term in email.lower() for term in BLACKLIST_TERMS):
                    valid_emails.add(email.lower())
    return valid_emails

# --- O ROBÔ ---
async def hunt_emails_on_web(domain: str) -> List[Dict]:
    """
    ESTRATÉGIA HÍBRIDA V3 (Smart Recon):
    1. Crawler: Varre o site e DESCOBRE o nome real da empresa (Title).
    2. Bing/Google: Usa o nome real descoberto para achar perfis.
    """
    clean_domain = domain.replace("http://", "").replace("https://", "").replace("www.", "").split("/")[0]
    # Nome de fallback caso o crawler falhe
    company_name_fallback = clean_domain.split('.')[0]
    real_company_name = None
    
    found_leads = []
    seen_emails = set()
    
    target_pages_keywords = ['contato', 'contact', 'sobre', 'about', 'equipe', 'team', 'quem-somos', 'quem_somos', 'fale-conosco', 'time', 'nosso-time']
    
    print(f"🚀 [INIT] Iniciando Caçada para: {clean_domain}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        
        # --- FASE 1: CRAWLER INTERNO (SENSING) ---
        print("🕷️ [FASE 1] Iniciando Crawler no Site Oficial...")
        page = await context.new_page()
        
        base_url = f"https://{clean_domain}"
        site_loaded = False
        
        try:
            try:
                await page.goto(base_url, timeout=12000)
                site_loaded = True
            except:
                print(f"   ⚠️ HTTPS falhou, tentando HTTP para {clean_domain}...")
                base_url = f"http://{clean_domain}"
                await page.goto(base_url, timeout=12000)
                site_loaded = True

            if site_loaded:
                # --- AUTO-DISCOVERY: Detecta nome real da empresa pelo Título ---
                try:
                    page_title = await page.title()
                    if page_title:
                        # Limpa termos comuns de SEO para tentar isolar o nome
                        clean_title = page_title.split('-')[0].split('|')[0].split(':')[0]
                        clean_title = clean_title.replace("Home", "").replace("Início", "").replace("Site Oficial", "").strip()
                        if len(clean_title) > 2:
                            real_company_name = clean_title
                            print(f"   💡 Nome da Empresa Identificado: '{real_company_name}'")
                except:
                    pass

                await asyncio.sleep(2)
                
                # 1.1: E-mails da Home
                content = await page.content()
                home_emails = extract_emails_from_text(content, clean_domain)
                for email in home_emails:
                    if email not in seen_emails:
                        print(f"   TEXTO ENCONTRADO (Home): {email}")
                        found_leads.append({"name": "Contato Site", "email": email, "linkedin": None, "role": "Site Oficial"})
                        seen_emails.add(email)

                # 1.2: Visitar links internos
                try:
                    all_links = await page.locator("a").all()
                    links_to_visit = set()
                    
                    for link in all_links:
                        try:
                            href = await link.get_attribute("href")
                            if href:
                                full_url = urllib.parse.urljoin(base_url, href)
                                if clean_domain in full_url and any(kw in full_url.lower() for kw in target_pages_keywords):
                                    links_to_visit.add(full_url)
                        except:
                            continue
                except:
                    pass

                for url in list(links_to_visit)[:5]: 
                    try:
                        print(f"   ↳ Visitando: {url}")
                        await page.goto(url, timeout=10000)
                        content = await page.content()
                        page_emails = extract_emails_from_text(content, clean_domain)
                        for email in page_emails:
                            if email not in seen_emails:
                                print(f"   TEXTO ENCONTRADO (Interna): {email}")
                                found_leads.append({"name": "Contato Interno", "email": email, "linkedin": None, "role": "Página Interna"})
                                seen_emails.add(email)
                    except:
                        continue
            else:
                print("   ⚠️ Não foi possível carregar o site da empresa.")

        except Exception as e:
            print(f"⚠️ Erro no Crawler do Site: {e}")

        # --- FASE 2: BING SEARCH (COM NOME REAL) ---
        print("\n🔍 [FASE 2] Iniciando Busca no Bing...")
        
        # Decide qual nome usar
        target_name = real_company_name if real_company_name else company_name_fallback
        
        # Estratégia de Queries (Mais específicas primeiro)
        search_queries = [
            f'site:linkedin.com/in/ "{target_name}" "{clean_domain}"', # Nome + Domínio (Altíssima precisão)
            f'site:linkedin.com/in/ "{target_name}" "Brasil"',         # Nome + País (Se for .br)
            f'site:linkedin.com/in/ "{target_name}"',                  # Nome isolado (pode ser genérico)
            f'site:linkedin.com/in/ "{clean_domain}"',                  # Domínio isolado
        ]
        
        # Se for .br, prioriza buscas locais
        if ".br" in domain:
             search_queries.insert(1, f'site:linkedin.com/in/ "{target_name}" "Brasil"')

        # Se o nome detectado for muito diferente do fallback, adiciona o fallback também

        bing_success = False

        for query in search_queries:
            if len([l for l in found_leads if l['linkedin']]) >= 15: break

            print(f"   ↳ Bing Query: {query}")
            try:
                encoded_query = urllib.parse.quote(query)
                bing_url = f"https://www.bing.com/search?q={encoded_query}&count=50"
                
                await page.goto(bing_url, timeout=20000)
                await asyncio.sleep(2)
                
                all_links = await page.locator("a").all()
                count_valid = 0
                
                for link in all_links:
                    try:
                        href = await link.get_attribute("href")
                        if not href or "linkedin.com/in/" not in href: continue
                        
                        title = await link.inner_text()
                        if not title: continue
                        
                        clean_title = title.split(" - LinkedIn")[0].split(" | LinkedIn")[0]
                        clean_title = clean_title.replace("...", "").replace("Perfil profissional", "").replace("Perfil", "").strip()

                        if any(x in clean_title.lower() for x in ["login", "vagas", "job", "company", "linkedin"]): continue

                        if len(clean_title.split()) < 2: continue
                        
                        separators = [" - ", " | ", ",", " – "]
                        name_raw = clean_title
                        role_raw = "Funcionário"
                        
                        found_sep = False
                        for sep in separators:
                            if sep in clean_title:
                                parts = clean_title.split(sep)
                                name_raw = parts[0].strip()
                                role_full = parts[1].strip()
                                role_raw = role_full.split(" na ")[0].split(" at ")[0].strip()
                                found_sep = True
                                break
                        
                        if len(name_raw.split()) < 2: continue
                        
                        name_parts = name_raw.split()
                        first = remove_accents(name_parts[0].lower())
                        last = remove_accents(name_parts[-1].lower())
                        
                        email_v1 = f"{first}.{last}@{clean_domain}"
                        
                        if email_v1 not in seen_emails:
                            # Filter Blacklist
                            if not any(term in email_v1.lower() for term in BLACKLIST_TERMS):
                                print(f"      👤 Bing Capturou: {name_raw} -> {role_raw}")
                                found_leads.append({"name": name_raw, "email": email_v1, "linkedin": href, "role": role_raw})
                                seen_emails.add(email_v1)
                                count_valid += 1
                                bing_success = True

                    except Exception as e:
                        continue
                
                print(f"      ✅ Leads nesta página: {count_valid}")

            except Exception as e:
                print(f"      ⚠️ Erro no Bing: {e}")
                continue

        # --- FASE 3: GOOGLE FALLBACK (Se Bing falhar ou trouxer poucos resultados) ---
        # Se achou menos de 3 leads no Bing, tenta o Google para complementar
        if len([l for l in found_leads if l['linkedin']]) < 3:
            print(f"\n⚠️ Bing retornou poucos resultados ({len([l for l in found_leads if l['linkedin']])}). Tentando Google (Fallback)...")
            try:
                # Usa query MAIS ESPECÍFICA no Google
                # Tenta: "NomeEmpresa" "dominio.com" site:linkedin.com/in/
                query = f'site:linkedin.com/in/ "{target_name}" "{clean_domain}" -intitle:jobs'
                encoded_query = urllib.parse.quote(query)
                google_url = f"https://www.google.com/search?q={encoded_query}&num=50&hl=pt-BR"
                
                await page.goto(google_url, timeout=20000)
                await asyncio.sleep(2)
                
                google_links = await page.locator("a").all()
                count_valid_google = 0
                
                for link in google_links:
                    try:
                        href = await link.get_attribute("href")
                        if not href or "linkedin.com/in/" not in href: continue
                        title = await link.inner_text()
                        if not title: continue
                        
                        clean_title = title.split(" - LinkedIn")[0].split(" | LinkedIn")[0].replace("...", "").replace("Perfil profissional", "").replace("Perfil", "").strip()
                        if any(x in clean_title.lower() for x in ["login", "vagas", "job"]): continue
                        
                        name_raw = clean_title.split(" - ")[0].split(" | ")[0].strip()
                        if len(name_raw.split()) < 2: continue
                        
                        name_parts = name_raw.split()
                        first = remove_accents(name_parts[0].lower())
                        last = remove_accents(name_parts[-1].lower())
                        email = f"{first}.{last}@{clean_domain}"
                        
                        if email not in seen_emails:
                            # Filter Blacklist
                            if not any(term in email.lower() for term in BLACKLIST_TERMS):
                                print(f"      👤 Google Capturou: {name_raw}")
                                found_leads.append({"name": name_raw, "email": email, "linkedin": href, "role": "Detectado via Google"})
                                seen_emails.add(email)
                                count_valid_google += 1
                    except: continue
                print(f"      ✅ Leads Google: {count_valid_google}")

            except Exception as e:
                print(f"⚠️ Erro no Google Fallback: {e}")

        await browser.close()

    # Fallback final (Genéricos) - SÓ SE NÃO ACHOU NADA MESMO
    if not found_leads:
        print("⚠️ Nada encontrado. Inserindo genéricos básicos.")
        common = ["contato", "adm", "comercial", "financeiro", "rh", "vendas"]
        for c in common:
            found_leads.append({"name": c.capitalize(), "email": f"{c}@{clean_domain}", "linkedin": None, "role": "Genérico"})
            
    print(f"🏁 [FIM] Varredura Completa. Total de Alvos: {len(found_leads)}")
    return found_leads