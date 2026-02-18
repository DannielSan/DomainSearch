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

def extract_emails_from_text(text: str, domain: str) -> Set[str]:
    """Regex poderoso para extrair e-mails de um texto cru"""
    if not text: return set()
    # Padrão que pega emails mesmo no meio de textos
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    matches = re.findall(email_pattern, text)
    valid_emails = set()
    for email in matches:
        if domain in email.lower(): # Garante que o e-mail é da empresa alvo
            # Filtra extensões de arquivo que parecem e-mail (ex: image@2x.png)
            if not email.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.css', '.js', '.webp')):
                valid_emails.add(email.lower())
    return valid_emails

# --- O ROBÔ ---
async def hunt_emails_on_web(domain: str) -> List[Dict]:
    """
    ESTRATÉGIA BING + CRAWLER:
    1. Crawler Interno: Varre Home + Páginas de "Contato/Equipe" em busca de e-mails REAIS.
    2. Bing Search: Busca perfis no LinkedIn via Bing (menos bloqueios que Google).
    """
    clean_domain = domain.replace("http://", "").replace("https://", "").replace("www.", "").split("/")[0]
    company_name = clean_domain.split('.')[0]
    
    found_leads = []
    seen_emails = set() # Evita duplicatas
    
    # Palavras-chave para encontrar páginas ricas em dados
    target_pages_keywords = ['contato', 'contact', 'sobre', 'about', 'equipe', 'team', 'quem-somos', 'quem_somos', 'fale-conosco', 'time', 'people']
    
    print(f"🚀 [INIT] Iniciando Caçada Híbrida (Bing + Crawler) para: {clean_domain}")

    async with async_playwright() as p:
        # headless=False para você VER o navegador abrindo
        browser = await p.chromium.launch(headless=False) 
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        
        # ==============================================================================
        # FASE 1: CRAWLER INTERNO (Busca e-mails escritos no site oficial)
        # ==============================================================================
        print("🕷️ [FASE 1] Iniciando Crawler no Site Oficial...")
        page = await context.new_page()
        
        try:
            base_url = f"https://{clean_domain}"
            try:
                await page.goto(base_url, timeout=15000)
            except:
                # Tenta http se https falhar
                base_url = f"http://{clean_domain}"
                await page.goto(base_url, timeout=15000)

            await asyncio.sleep(2)
            
            # 1.1: Extrai e-mails da Home
            content = await page.content()
            home_emails = extract_emails_from_text(content, clean_domain)
            for email in home_emails:
                if email not in seen_emails:
                    print(f"   TEXTO ENCONTRADO (Home): {email}")
                    found_leads.append({"name": "Contato Site", "email": email, "linkedin": None, "role": "Site Oficial"})
                    seen_emails.add(email)

            # 1.2: Procura links internos (Contato, Sobre, etc)
            all_links = await page.locator("a").all()
            links_to_visit = set()
            
            for link in all_links:
                href = await link.get_attribute("href")
                if href:
                    # Resolve URL relativa (/contato -> https://site.com/contato)
                    full_url = urllib.parse.urljoin(base_url, href)
                    # Só visita se for do mesmo domínio e tiver palavra chave
                    if clean_domain in full_url and any(kw in full_url.lower() for kw in target_pages_keywords):
                        links_to_visit.add(full_url)
            
            print(f"   ↳ Links internos identificados: {len(links_to_visit)}")

            # 1.3: Visita as páginas internas (Limitado a 5 para velocidade)
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

        except Exception as e:
            print(f"⚠️ Erro no Crawler do Site: {e}")

        # ==============================================================================
        # FASE 2: BING SEARCH (Substituto superior ao Google para Scraping)
        # ==============================================================================
        print("\n🔍 [FASE 2] Iniciando Busca no Bing (LinkedIn)...")
        
        # Queries otimizadas para o Bing
        search_queries = [
            f'site:linkedin.com/in/ "{clean_domain}"', 
            f'site:linkedin.com/in/ "{company_name}"',
            f'{clean_domain} "email" site:linkedin.com/in/'
        ]

        for query in search_queries:
            # Se já achamos mais de 15 pessoas, para
            if len([l for l in found_leads if l['linkedin']]) >= 15: break

            print(f"   ↳ Bing Query: {query}")
            try:
                encoded_query = urllib.parse.quote(query)
                # Bing usa parametros diferentes do Google
                bing_url = f"https://www.bing.com/search?q={encoded_query}&count=50"
                
                await page.goto(bing_url, timeout=20000)
                await asyncio.sleep(3)
                
                # O Bing estrutura resultados em listas 'li.b_algo'
                results = await page.locator("li.b_algo h2 a").all()
                
                if len(results) == 0:
                    print("      ⚠️ Bing retornou 0 resultados (pode ser captcha ou vazio).")
                
                for link in results:
                    title = await link.inner_text()
                    href = await link.get_attribute("href")
                    
                    if not href or "linkedin.com/in/" not in href: continue
                    
                    # Limpeza do Título (Bing: "Nome Sobrenome - Cargo - LinkedIn")
                    clean_title = title.split(" - LinkedIn")[0].split(" | LinkedIn")[0]
                    
                    # Filtros de Lixo
                    if any(x in clean_title.lower() for x in ["perfil", "login", "vagas", "job", "company", "linkedin"]): continue

                    # Parser de Nome
                    separators = [" - ", " | ", ","]
                    name_raw = clean_title
                    role_raw = "Funcionário"
                    
                    for sep in separators:
                        if sep in clean_title:
                            parts = clean_title.split(sep)
                            name_raw = parts[0].strip()
                            role_raw = parts[1].strip()
                            break
                    
                    # Validação mínima
                    if len(name_raw.split()) < 2: continue

                    # Geração de E-mail (Variações)
                    name_parts = name_raw.split()
                    first = remove_accents(name_parts[0].lower())
                    last = remove_accents(name_parts[-1].lower())
                    
                    # Gera 2 tipos de email
                    email_v1 = f"{first}.{last}@{clean_domain}" # padrao.comum
                    email_v2 = f"{first}@{clean_domain}"       # curto
                    
                    if email_v1 not in seen_emails:
                        print(f"      👤 Bing Encontrou: {name_raw}")
                        found_leads.append({
                            "name": name_raw,
                            "email": email_v1,
                            "linkedin": href,
                            "role": role_raw
                        })
                        seen_emails.add(email_v1)
                    
                    # Adiciona a variação curta também para testar depois
                    if email_v2 not in seen_emails:
                        found_leads.append({
                            "name": name_raw,
                            "email": email_v2,
                            "linkedin": href,
                            "role": role_raw
                        })
                        seen_emails.add(email_v2)

            except Exception as e:
                print(f"      ⚠️ Erro no Bing: {e}")
                continue

        await browser.close()

    # Fallback apenas se falhar tudo
    if not found_leads:
        print("⚠️ Nada encontrado. Inserindo genéricos básicos.")
        common = ["contato", "adm", "comercial"]
        for c in common:
            found_leads.append({
                "name": c.capitalize(),
                "email": f"{c}@{clean_domain}",
                "linkedin": None,
                "role": "Genérico"
            })

    print(f"🏁 [FIM] Varredura Completa. Total de Alvos: {len(found_leads)}")
    return found_leads