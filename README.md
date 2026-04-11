# 🏆 TenderAI — The Future of Public Procurement

**TenderAI** is a premium, automated platform designed to help Moroccan enterprises dominate the public tender (Appel d'Offres) market. Using a high-fidelity **Stitch UI** and an advanced multi-provider AI pipeline, TenderAI extracts requirements, generates compliant dossiers in administrative French, and performs self-correcting audits.

---

## 🚀 Key Features

### 💎 Premium Dashboard (Stitch UI)
- **High-Fidelity Visuals**: Glassmorphism design with vibrant executive aesthetics.
- **Confidence Gauge**: Real-time compliance scoring (0-100%) to predict tender success.
- **AI Processing Pipeline**: Watch the extraction, generation, and validation steps in real-time.

### 🧠 Intelligent Backend (The Enforcer)
- **Multi-Phase Extraction**: Robust PDF parsing to identify mandatory documents and technical specs.
- **Dossier Generation (Gemini)**: Professional administrative French writing tailored to company profiles.
- **Compliance Audit (Mistral/Featherless)**: A strict auditor layer that identifies missing sections and non-compliant clauses.
- **Self-Correction Loop**: If the auditor finds weaknesses (score < 70), the writer automatically regenerates the dossier for perfect compliance.

### 🗃️ Persistent Memory
- **Full Traceability**: Tenders, offers, and evaluations are stored in a persistent PostgreSQL database.
- **Secure File Vault**: Original tender documents and generated dossiers are stored with SHA-256 integrity proofs.

---

## 🛠 Tech Stack
- **Frontend**: React 18, Vite, Lucide Icons, Glassmorphism CSS.
- **Backend**: FastAPI (Python 3.12), SQLAlchemy 2, Pydantic v2.
- **Processing**: Redis + Celery (Background Processing-ready).
- **AI Models**: Google Gemini 2.0 Flash (Generation) & Mistral-Large via Featherless (Validation).

---

## 🚦 Getting Started (The 60-Second Demo)

The entire platform is fully containerized. You can launch the database, the backend engine, and the premium dashboard with a single command.

### 1. Prerequisites
- Docker & Docker Compose
- API Keys in `.env` (`GEMINI_API_KEY`, `FEATHERLESS_API_KEY`)

### 2. Launch the Platform
```bash
docker compose up --build
```

### 3. Access the Dashboard
- **Frontend**: [http://localhost:3000](http://localhost:3000)
- **API (Swagger Docs)**: [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)

---

## 📂 Project Structure
- `/app` — FastAPI application core (Models, API, Services).
- `/frontend` — React dashboard and Stitch UI components.
- `/data` — Secure file vault for PDF storage.
- `/scripts` — Utility scripts for testing and database migrations.

---

**Developed for the Hackathon 2026. Ready for the Main Stage.** 🏆
