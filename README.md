# Shopify Live Concierge: The Multimodal AI Assistant — Backend (FastAPI)

[![Powered by Google Gemini](https://img.shields.io/badge/Powered%20by-Google%20Gemini-4285F4?logo=google-gemini&logoColor=white)](https://ai.google.dev/)
[![GCP Cloud Run](https://img.shields.io/badge/Deployed%20to-Google%20Cloud%20Run-4285F4?logo=google-cloud&logoColor=white)](https://cloud.google.com/run)

The intelligent brain of the **Shopify Live Concierge: The Multimodal AI Assistant**, a multimodal agentic system built for the **Gemini Live Agent Challenge**. This backend orchestrates real-time voice interactions, visual product search, and automated cart management using Google Gemini 2.0.

## 🚀 Key Features

- **Gemini Multimodal Live API**: Low-latency WebSocket relay for real-time voice interactions.
- **Multimodal RAG Pipeline**: Product semantic search using CLIP embeddings and Pinecone Serverless.
- **Shopify Agentic Tools**: Automated cart management, order tracking, and history-based personalization via Shopify GraphQL.
- **RAG Monitoring & Evaluation**: Built-in metrics (NDCG, Hit Rate, MRR) and search logging to track retrieval quality.
- **Security**: Fernet symmetric encryption for Shopify tokens at rest, integrated with GCP Secret Manager.

## 🛠️ Technology Stack

- **Framework**: FastAPI (Python 3.12)
- **AI**: Gemini 2.0 Flash (Text/Vision) & Gemini 2.0 Flash-Live (Voice)
- **Database**: PostgreSQL (Supabase) via Prisma Client Python
- **Vector DB**: Pinecone Serverless (GRPC)
- **Embeddings**: CLIP via HuggingFace Transformers
- **Infrastructure**: Google Cloud Run, Cloud Build, Secret Manager

---

## 💻 Local Setup Instructions

### 1. Prerequisites
- Python 3.11+
- PostgreSQL database
- Pinecone Account
- Google AI Studio (Gemini) API Key

### 2. Installation
```bash
# Clone the repository
git clone <your-repo-url>
cd shopify-ai-concierge-backend

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Variables
Create a `.env` file in the root based on `.env.example`:
```env
# Database
DATABASE_URL="postgresql://..."

# Keys
GEMINI_API_KEY="your-key"
PINECONE_API_KEY="your-key"
PINECONE_INDEX_NAME="shopify-ai-rag"
FERNET_SECRET_KEY="generate-one-using-cryptography"
JWT_SECRET_KEY="random-string"

# Shopify (for dev)
SHOPIFY_API_VERSION="2026-01"
```

### 4. Database Setup
```bash
# Push schema and generate Prisma client
prisma db push
prisma generate
```

### 5. Run the Server
```bash
uvicorn app.main:app --reload
```

---

## ☁️ Google Cloud Deployment

The project is designed for **Google Cloud Run**. The `cloudbuild.yaml` file automates the containerization and deployment process, including secure secret injection from **Secret Manager**.

### CI/CD Flow:
1. Push to `main` branch.
2. Cloud Build triggers.
3. Secrets are pulled from GCP Secret Manager.
4. Image is built and pushed to Artifact Registry.
5. Service is deployed to Cloud Run with auto-scaling enabled.

---

## 🧪 Reproducible Testing (For Judges)

### 1. Verification of Gemini Live API (Voice)
To verify the real-time voice relay without a full Shopify store:
1.  Ensure `GEMINI_API_KEY` is set in `.env`.
2.  Start the server (`uvicorn app.main:app`).
3.  The backend establishes a WebSocket relay at `/api/public/{slug}/live-relay`.
4.  You can use the frontend "Concierge" mic button to initiate the PCM 16-bit 16kHz audio stream.
5.  Check logs: You should see `[LiveRelay] Client connected` followed by `[LiveRelay] Sending setup to Gemini...`.

### 2. Monitoring the RAG Evaluator
1.  Perform any search on the storefront.
2.  Navigate to the `/api/store/{store_id}/rag/metrics` endpoint (or use the Admin Dashboard).
3.  Verify that it returns a JSON object with `ndcg`, `mrr`, and `hit_rate` calculated from your search events.

### 3. Automated Deployment Proof
Inspect `cloudbuild.yaml`. This file proves the infrastructure is "Reproducible" via code (IaC), managing the build, containerization, and secret injection from GCP Secret Manager automatically on every push to `main`.
