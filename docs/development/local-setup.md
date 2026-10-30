# EduIntel AI — Local Development Setup Guide

This guide provides step-by-step instructions for configuring and running the complete EduIntel AI development environment on a local Linux or WSL2 Ubuntu workstation on branch `develop/production-readiness`.

---

## 1. Prerequisites & Tooling

Ensure the following tools are installed on your host system:

| Tool | Required Version | Verification Command | Installation Instructions |
|---|---|---|---|
| **Python** | 3.12+ | `python3 --version` | `sudo apt install python3.12 python3.12-venv python3-pip` |
| **Node.js** | 20+ (with npm) | `node --version && npm --version` | NodeSource or `nvm install 20` |
| **Docker** | 24+ | `docker --version` | Standard Docker Engine installation |
| **Docker Compose**| v2+ | `docker compose version` | Bundled with Docker Engine |
| **Tesseract OCR** | 5+ | `tesseract --version` | `sudo apt install tesseract-ocr libtesseract-dev` |
| **Git** | 2.40+ | `git --version` | `sudo apt install git` |

---

## 2. Environment Configuration

### 2.1. Clone Repository & Switch Branch
```bash
git clone https://github.com/your-org/eduintel.git
cd eduintel
git checkout develop/production-readiness
```

### 2.2. Backend Environment Variables (`backend/.env`)
Create `backend/.env` containing the required configuration parameters:

```env
# Relational Database (PostgreSQL 16 via Docker Compose)
DATABASE_URL=postgresql+asyncpg://eduintel:eduintel_dev@localhost:5432/eduintel

# Authentication & Security
JWT_SECRET_KEY=development_jwt_secret_key_change_in_production_min_32_chars
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=43200

# Artificial Intelligence & LLM Providers
GEMINI_API_KEY=your_google_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here

# Local Upload & Storage Paths
UPLOAD_DIR=uploads/
CHROMA_PERSIST_DIR=chroma_data/
```

> [!WARNING]
> Never commit `backend/.env` to source control. It is ignored by `.gitignore`.

---

## 3. Launching Local Services

### Step 1: Start PostgreSQL via Docker Compose
In the `backend/` directory:
```bash
cd backend
docker compose up -d

# Verify PostgreSQL is running and healthy on port 5432
docker compose ps
```

### Step 2: Initialize Python Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: Run Database Migrations
Apply all 20 Alembic migrations to construct the database schema:
```bash
alembic upgrade head

# Verify active revision
alembic current
```

### Step 4: Seed Development Data (Optional)
If you wish to populate initial test users and sample class data:
```bash
python -m app.core.seed_data
```

### Step 5: Start FastAPI Backend Development Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
- API Base: `http://localhost:8000`
- Interactive Swagger UI: `http://localhost:8000/docs`
- ReDoc UI: `http://localhost:8000/redoc`

---

## 4. Frontend Application Setup

In a new terminal window:

```bash
cd frontend

# Install Node dependencies
npm install

# Start Vite development server
npm run dev
```
- Frontend Web App: `http://localhost:5173`
- Default Vite proxy forwards `/api/*` requests to `http://localhost:8000`.

---

## 5. Verification Checklist

Run through these checks to ensure your local installation is fully functional:

- [ ] `curl http://localhost:8000/health` returns `{"status": "healthy", "database": "connected"}`.
- [ ] Swagger docs load at `http://localhost:8000/docs` with all 57 endpoints listed.
- [ ] Login screen opens at `http://localhost:5173/login`.
- [ ] Tests run successfully:
  ```bash
  cd backend
  ./venv/bin/pytest -v
  ```

---

## 6. Common Troubleshooting

### Issue: Port 5432 already in use
- **Cause**: A local PostgreSQL system service is already running on port 5432.
- **Fix**: Either stop the host service (`sudo systemctl stop postgresql`) or change the mapped port in `backend/docker-compose.yml` (e.g. `"5434:5432"`) and update `DATABASE_URL` in `.env`.

### Issue: `ModuleNotFoundError: No module named 'tesseract'`
- **Cause**: Missing system library for OCR.
- **Fix**: Install Tesseract OCR: `sudo apt install tesseract-ocr`.

