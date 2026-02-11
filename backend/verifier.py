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
        # Conecta ao servidor com timeout curto (3s) para não travar a API
        server = smtplib.SMTP(timeout=3)
        server.set_debuglevel(0)
        
        # Tenta conectar
        server.connect(mx_record, 25)
        server.helo('CheckMyEmail') 
        
        # Simula envio
        server.mail('test@example.com')
        code, message = server.rcpt(email)
        server.quit()

        if code == 250:
            return "valid"
        elif code == 550:
            return "invalid"
        else:
            return "risky" # Servidor respondeu algo estranho (Greylisting, etc)

    except Exception:
        return "risky" # Firewall ou bloqueio impediu o teste