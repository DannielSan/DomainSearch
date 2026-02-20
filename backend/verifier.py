import smtplib
import dns.resolver
import re
import socket

def verify_email_realtime(email: str):
    """
    Verifica se um e-mail é válido tecnicamente.
    Retorna: 'valid', 'invalid', ou 'risky'
    """
    # 1. Sintaxe Básica
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return "invalid"

    domain = email.split('@')[1]

    # 2. Verifica DNS (MX Record)
    try:
        records = dns.resolver.resolve(domain, 'MX')
        mx_record = str(records[0].exchange)
    except:
        return "invalid" # Domínio não tem e-mail configurado

    # 3. Simulação de SMTP (Ping no Servidor)
    try:
        server = smtplib.SMTP(timeout=3)
        server.set_debuglevel(0)
        
        # Tenta conectar
        server.connect(mx_record, 25)
        server.helo('CheckMyEmail') 
        
        # --- CATCH-ALL DETECTOR ---
        # Ping com e-mail garantidamente falso para ver se o servidor aceita tudo
        fake_email = f"xjzqw91823_pingtest@{domain}"
        server.mail('test@example.com')
        catchall_code, _ = server.rcpt(fake_email)
        
        is_catch_all = (catchall_code == 250)
        
        # --- TESTE REAL DO E-MAIL ALVO ---
        server.mail('test@example.com') # Reseta correio
        code, message = server.rcpt(email)
        server.quit()

        if code == 250:
            if is_catch_all:
                return "risky" # É catch-all, então o "OK" não garante que a pessoa exista
            return "valid"
        elif code == 550:
            return "invalid"
        else:
            return "risky" 

    except Exception:
        return "risky"