from playwright.async_api import async_playwright
import re
import urllib.parse
import unicodedata
import asyncio

def remove_accents(input_str):
    if not input_str:
        return ""
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

async def hunt_emails_on_web(domain: str):
    """
    Estratégia Deep Harvest (Força Bruta V2):
    1. Queries Globais (sem restrição de BR).
    2. Filtragem Ativa de Lixo (jobs, company, pulse).
    3. Parser Tolerante a Falhas.
    """
    clean_domain = domain.replace("http://", "").replace("https://", "").replace("www.", "").split("/")[0]
    company_raw = clean_domain.split('.')[0] # ex: opentreinamentos
    
    # --- LISTA DE TENTATIVAS DE BUSCA ---
    # Removido "br." para pegar perfis globais e evitar filtro excessivo
    search_queries = [
        f'site:linkedin.com/in/ "{clean_domain}"',       # Domínio exato no perfil
        f'site:linkedin.com/in/ "{company_raw}"',        # Nome da empresa (aspas)
        f'site:linkedin.com/in/ {company_raw} -intitle:jobs -intitle:company', # Nome solto + filtros
        f'"{company_raw}" site:linkedin.com/in/ email'    # Tentativa de achar quem expõe email
    ]
    
    found_leads = []
    seen_keys = set() 

    # --- 1. Genéricos (Base de segurança) ---
    common_prefixes = ["contato", "comercial", "financeiro", "rh", "vendas", "adm", "suporte", "diretoria"]
    for prefix in common_prefixes:
        email = f"{prefix}@{clean_domain}"
        key = email
        if key not in seen_keys:
            found_leads.append({
                "name": prefix.capitalize(),
                "email": email,
                "linkedin": None,
                "role": "Departamento"
            })
            seen_keys.add(key)

    # --- 2. Busca Profunda no Google ---
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False) # Mantenha False para debug visual se necessário
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print(f"🕵️‍♂️ Iniciando Varredura Profunda V2 para: {clean_domain}")

        for query in search_queries:
            # Se já temos uma boa quantidade de leads reais (ex: 15), pula o resto
            real_people = [l for l in found_leads if l['linkedin']]
            if len(real_people) >= 15:
                break

            print(f"   ↳ Tentando query: {query}")
            
            try:
                encoded_query = urllib.parse.quote(query)
                # num=100 para pegar máximo possível por página
                google_url = f"https://www.google.com/search?q={encoded_query}&num=100&hl=pt-BR"
                
                await page.goto(google_url, timeout=30000)
                await asyncio.sleep(3 + (len(found_leads) * 0.1)) # Delay dinâmico leve

                # Check Captcha
                if await page.locator("text=recaptcha").count() > 0:
                    print("⚠️ CAPTCHA! Resolva manualmente...")
                    while await page.locator("text=recaptcha").count() > 0:
                        await asyncio.sleep(1)
                    await asyncio.sleep(2)

                # Coletar Links
                all_links = await page.locator("a").all()
                extracted_count = 0
                
                for link in all_links:
                    try:
                        href = await link.get_attribute("href")
                        if not href or "linkedin.com/in/" not in href:
                            continue

                        # Filtros de URL suja
                        if any(x in href for x in ["/jobs/", "/company/", "/pulse/", "/dir/", "/learning/", "/posts/"]):
                            continue

                        title = await link.inner_text()
                        if not title: continue

                        # Limpeza do Título
                        # Google costuma retornar: "Nome Sobrenome - Cargo - Empresa | LinkedIn"
                        # Ou: "Nome Sobrenome | LinkedIn"
                        clean_title = title
                        for suffix in [" - LinkedIn", " | LinkedIn", " | LinkedIn Brasil"]:
                            clean_title = clean_title.split(suffix)[0]
                        clean_title = clean_title.replace("...", "").strip()

                        # Filtros de Título sujo (termos genéricos que aparecem na busca)
                        junk_terms = ["perfil", "login", "cadastre-se", "vagas", "pessoas também viram", "outros perfis", "traduzir esta página"]
                        if any(term in clean_title.lower() for term in junk_terms):
                            continue

                        # Parser de Nome e Cargo
                        # Tenta quebrar por separadores comuns
                        separators = [" - ", " – ", " | ", ","]
                        name_raw = clean_title
                        role_raw = "Funcionário"

                        found_sep = False
                        for sep in separators:
                            if sep in clean_title:
                                parts = clean_title.split(sep)
                                name_raw = parts[0].strip()
                                # O resto é cargo/empresa
                                role_full = parts[1].strip()
                                # Tenta limpar empresa do cargo (ex: "Gerente na Open")
                                role_raw = role_full.split(" na ")[0].split(" da ")[0].split(" at ")[0].strip()
                                found_sep = True
                                break
                        
                        # Se não achou separador, assume que o título inteiro é o nome (comum em perfis sem cargo no título)
                        
                        # Validação de Nome (Mínimo 2 partes, sem números)
                        if len(name_raw.split()) < 2 or any(char.isdigit() for char in name_raw):
                            continue

                        # Geração de E-mail
                        name_parts = name_raw.split()
                        first = remove_accents(name_parts[0].lower())
                        last = remove_accents(name_parts[-1].lower()) # Pega o último sobrenome para garantir
                        
                        # Estratégia: primeiro.ultimo
                        generated_email = f"{first}.{last}@{clean_domain}"
                        
                        # Deduplicação baseada no LinkedIn (mais confiável que email gerado)
                        if href not in seen_keys:
                            print(f"      👤 Capturado: {name_raw} -> {role_raw}")
                            found_leads.append({
                                "name": name_raw,
                                "email": generated_email,
                                "linkedin": href,
                                "role": role_raw
                            })
                            seen_keys.add(href)
                            seen_keys.add(generated_email) # Evita gerar o mesmo email para pessoas diferentes (colisão simples)
                            extracted_count += 1
                            
                    except Exception as e:
                        # print(f"Erro item: {e}")
                        continue

                print(f"      ✅ Extraídos nesta página: {extracted_count}")

            except Exception as e:
                print(f"⚠️ Erro query '{query}': {e}")
                continue

        await browser.close()

    print(f"🏁 Varredura finalizada. Total de leads: {len(found_leads)}")
    return found_leads