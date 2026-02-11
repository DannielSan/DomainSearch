from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# --- CONFIGURAÇÃO CRÍTICA DO MYSQL ---
# Substitua 'root' pelo seu usuário (geralmente é root)
# Substitua 'sua_senha' pela senha do seu MySQL (se não tiver, deixe vazio ou verifique sua config)
# 'localhost' é o endereço do servidor
# 'domainsearch' é o nome do banco que criamos no passo 1
SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:12170220@localhost:3306/domainsearch"

# pool_recycle=3600 é vital para MySQL: evita que a conexão caia por inatividade
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    pool_recycle=3600
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Dependência para injetar o banco nas rotas
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()