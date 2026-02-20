from datetime import datetime, timedelta
from typing import Optional
from passlib.context import CryptContext
from jose import JWTError, jwt
from fastapi import Request, Depends, HTTPException, status
from sqlalchemy.orm import Session
import models
from database import get_db

SECRET_KEY = "domainsearch_super_secret_key_2025_xtreme" # Idealmente em um .env
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30 # Um mês de sessão (Manter conectado)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Dependência do FastAPI para verificar quem é o usuário logado lendo os Cookies
async def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("session_token")
    if not token:
        return None
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None
        
    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    return user

async def get_current_active_user(current_user: models.User = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Não autenticado.",
            headers={"Location": "/login"}
        )
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Usuário inativo.")
    return current_user

async def get_current_admin_user(current_user: models.User = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"}
        )
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Não tem permissão de administrador."
        )
    return current_user
