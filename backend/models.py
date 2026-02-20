from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from database import Base
import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    cpf = Column(String(20), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="employee") # "admin" or "employee"
    is_active = Column(Boolean, default=True)
    # Relacionamento Inverso
    companies = relationship("Company", back_populates="owner")
    leads = relationship("Lead", back_populates="owner")

class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String(255), index=True) # ex: opentreinamentos.com.br
    name = Column(String(255))               # ex: Open Soluções
    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relacionamento
    owner = relationship("User", back_populates="companies")
    leads = relationship("Lead", back_populates="company")

class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    email = Column(String(255), index=True)
    job_title = Column(String(150))      # Cargo
    linkedin_url = Column(String(500))   # Link do perfil
    confidence_score = Column(Integer)   # 0 a 100%
    status = Column(String(50))          # valid, invalid, risky
    is_saved = Column(Boolean, default=False) # Adição manual (botão +)
    saved_at = Column(DateTime, nullable=True) # Data em que foi salvo no CRM
    
    # Chave estrangeira ligando à empresa
    company_id = Column(Integer, ForeignKey("companies.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    
    company = relationship("Company", back_populates="leads")
    owner = relationship("User", back_populates="leads")