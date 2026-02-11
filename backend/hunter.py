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
    Estratégia Flexível:
    1. Busca ampla no Google (sem aspas rígidas).
    2. Espera inteligente pelos resultados.
    3. Captura robusta de links.
    """
    clean_domain = domain.replace("http://", "").replace("https://", "").replace("www.", "").split("/")[0]
    # Remove .com.br para pegar o nome "cru" (ex: opentreinamentos)
    company_name_guess = clean_domain.split('.')[0]
    
    found_leads = []
    seen_emails = set()

    # --- 1. Genéricos (Base de segurança) ---
    common_prefixes = ["contato", "comercial", "financeiro", "rh", "vendas", "adm", "suporte", "diretoria"]
    for prefix in common_prefixes:
        email = f"{prefix}@{clean_domain}"
        found_leads.append({
            "name": prefix.capitalize(),
            "email": email,
            "linkedin": None,
            "role": "Departamento"
        })
        seen_emails.add(email)

    # --- 2. Busca no Google (Modo Visual) ---
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False) 
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print(f"🕵️‍♂️ Buscando funcionários da '{company_name_guess}' no Google...")

        try:
            # MUDANÇA 1: Removemos as aspas do nome da empresa para o Google achar variações (Open Treinamentos)
            # Query: site:linkedin.com/in/ opentreinamentos "Salvador" (opcional, ajuda a filtrar)
            query = f'site:linkedin.com/in/ {company_name_guess}'
            
            encoded_query = urllib.parse.quote(query)
            # Adicionei &num=50 para pegar mais resultados de uma vez
            google_url = f"https://www.google.com/search?q={encoded_query}&num=50&hl=pt-BR"
            
            await page.goto(google_url, timeout=30000)
            
            # MUDANÇA 2: Espera explícita pelo container de resultados
            try:
                await page.wait_for_selector("#search", timeout=10000)
            except:
                print("⚠️ Demorou para carregar os resultados ou caiu em Captcha.")
            
            # Pequena pausa humana
            await asyncio.sleep(2)

            # MUDANÇA 3: Pega TODOS os links da área de busca, não importa a estrutura
            # O seletor #search a busca apenas dentro dos resultados reais (ignora anúncios as vezes)
            linkedin_links = await page.locator("#search a[href*='linkedin.com/in/']").all()
            
            print(f"🔎 O Google retornou {len(linkedin_links)} perfis brutos.")

            for link in linkedin_links:
                try:
                    href = await link.get_attribute("href")
                    title = await link.inner_text()
                    
                    if not title or not href:
                        continue

                    # Limpeza clássica do título
                    title = title.split(" - LinkedIn")[0].split(" | LinkedIn")[0]
                    
                    # Ignora links de "Vagas", "Empresa" ou "Pulse"
                    if "/jobs/" in href or "/company/" in href or "/pulse/" in href:
                        continue

                    # Tenta separar Nome e Cargo
                    # Ex: "Soraya Sá - Diretora Comercial"
                    if "-" in title:
                        parts = title.split("-")
                        name_raw = parts[0].strip()
                        role_raw = parts[1].strip() if len(parts) > 1 else "Funcionário"
                    else:
                        name_raw = title.strip()
                        role_raw = "Funcionário"

                    # Filtro final de lixo
                    if "perfil" in name_raw.lower() or "linkedin" in name_raw.lower():
                        continue

                    # Gera o e-mail
                    name_parts = name_raw.split(" ")
                    if len(name_parts) >= 1:
                        first_name = remove_accents(name_parts[0].lower())
                        last_name = remove_accents(name_parts[-1].lower()) if len(name_parts) > 1 else ""
                        
                        # Gera e-mail: nome.sobrenome@dominio
                        if last_name:
                            generated_email = f"{first_name}.{last_name}@{clean_domain}"
                        else:
                            generated_email = f"{first_name}@{clean_domain}"
                        
                        if generated_email not in seen_emails:
                            print(f"   👤 Encontrado: {name_raw}")
                            found_leads.append({
                                "name": name_raw,
                                "email": generated_email,
                                "linkedin": href,
                                "role": role_raw
                            })
                            seen_emails.add(generated_email)

                except Exception as e:
                    continue

        except Exception as e:
            print(f"⚠️ Erro na busca: {e}")

        await browser.close()

    return found_leads