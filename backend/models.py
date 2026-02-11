from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from database import Base
import datetime

class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String(255), unique=True, index=True) # ex: opentreinamentos.com.br
    name = Column(String(255))                            # ex: Open Soluções
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relacionamento: Uma empresa tem muitos leads
    leads = relationship("Lead", back_populates="company")

class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    email = Column(String(255), unique=True, index=True)
    job_title = Column(String(150))      # Cargo
    linkedin_url = Column(String(500))   # Link do perfil
    confidence_score = Column(Integer)   # 0 a 100%
    status = Column(String(50))          # valid, invalid, risky
    
    # Chave estrangeira ligando à empresa
    company_id = Column(Integer, ForeignKey("companies.id"))
    company = relationship("Company", back_populates="leads")