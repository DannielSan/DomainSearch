import sys
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import models
from database import SQLALCHEMY_DATABASE_URL

def run_migration():
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    try:
        # Encontra o Admin Principal
        admin_email = "dsbarrettoo@gmail.com"
        admin = db.query(models.User).filter(models.User.email == admin_email).first()
        
        if not admin:
            print("ERRO CRITICO: Admin não encontrado. Suba o servidor main.py primeiro para criar o admin master.")
            sys.exit(1)
            
        print(f"[*] Inciando o The Great Purge: Transferindo posse para o Lord {admin_email} (ID: {admin.id})")
        
        from sqlalchemy import text
        
        # 1. Ajustando a Estrutura (Raw SQL para adicionar colunas)
        # Vamos usar try-except pois pode já ter rodado
        try:
            db.execute(text("ALTER TABLE companies ADD COLUMN user_id INTEGER;"))
            db.execute(text("ALTER TABLE companies ADD CONSTRAINT fk_company_user FOREIGN KEY(user_id) REFERENCES users(id);"))
            print("  [+] Coluna user_id adicionada em companies.")
        except Exception as e:
            print(f"  [~] Aviso: user_id em companies {e}")
            
        try:
            db.execute(text("ALTER TABLE leads ADD COLUMN user_id INTEGER;"))
            db.execute(text("ALTER TABLE leads ADD CONSTRAINT fk_lead_user FOREIGN KEY(user_id) REFERENCES users(id);"))
            print("  [+] Coluna user_id adicionada em leads.")
        except Exception as e:
            print(f"  [~] Aviso: user_id em leads {e}")
            
        # 2. Retirando travas globais de UNIQUE (O MySQL exige deletar o index)
        try:
            db.execute(text("ALTER TABLE companies DROP INDEX ix_companies_domain;")) 
            print("  [+] Trava global de dominio (Company) quebrada.")
        except Exception as e:
            print(f"  [~] Aviso index company: {e}")

        try:
            db.execute(text("ALTER TABLE leads DROP INDEX ix_leads_email;"))
            print("  [+] Trava global de email (Lead) quebrada.")
        except Exception as e:
            print(f"  [~] Aviso index lead: {e}")
            

        # 3. Herança de Dados (Update em massa)
        db.execute(text(f"UPDATE companies SET user_id = {admin.id} WHERE user_id IS NULL;"))
        db.execute(text(f"UPDATE leads SET user_id = {admin.id} WHERE user_id IS NULL;"))
        
        db.commit()
        print("[*] SUCESSO ABSOLUTO: Todas as entidades agora pertencem ao dono!")
        
    except Exception as e:
        db.rollback()
        print(f"ERRO FATAL: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    run_migration()
