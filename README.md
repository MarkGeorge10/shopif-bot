# Shopify Live Concierge: The Multimodal AI Assistant — Backend (FastAPI)

## 🏆 Gemini Live Agent Challenge Submission

### 🔑 Test Credentials (Judges)
| Access Point | Username / Email | Password |
| :--- | :--- | :--- |
| **Merchant Dashboard** | `mark@example.com` | `12345678` |
| **Shopify Checkout** | *(If prompted)* | `rteong` |

---

## 1. Project Overview
**Shopify Live Concierge** is a multimodal AI shopping assistant that transforms any Shopify store into an intelligent conversational shopping experience powered by **Google Gemini**.

The backend serves as the agentic orchestrator, coordinating between Gemini 2.0 Flash (Live), Shopify GraphQL APIs, and Pinecone vector search for a seamless, multimodal merchant experience.

## 2. Key Features and Functionality

### 2.1 Multimodal Reasoning
- **Gemini 2.0 Flash**: Primary logic engine for text and image reasoning.
- **Multimodal Live Relay**: Low-latency WebSocket handler for real-time voice (PCM 16-bit 16kHz).
- **CLIP Embeddings**: Local embedding generation for visual product discovery.

### 2.2 Agentic Shopify Integration
The AI assistant is equipped with specialized tools for:
- **Cart CRUD**: Automated shopping cart management via Storefront API.
- **Order Tracking**: Retrieval of real-time fulfillment data via Admin API.
- **Merchant Management**: Analytics, store indexing, and configuration logs.

### 2.3 RAG Monitoring & Evaluation
A dedicated evaluation engine calculates real-time quality metrics:
- **NDCG** (Normalized Discounted Cumulative Gain)
- **Hit Rate**
- **Search Latency** (p50/p95 tracking)

## 🛠️ Technology Stack
- **Framework**: FastAPI (Python 3.12)
- **Database**: PostgreSQL (Supabase) via Prisma Client Python
- **Vector DB**: Pinecone Serverless
- **Security**: Fernet symmetric encryption for tokens at rest
- **Infrastructure**: Google Cloud Run, Secret Manager

---

## 💻 Local Setup Instructions

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/MarkGeorge10/shopif-bot
cd shopify-ai-concierge-backend

# Setup environment
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Database & RAG Setup
```bash
# Generate Prisma client and sync schema
prisma db push
prisma generate
```

### 3. Run the Server
```bash
uvicorn app.main:app --reload
```

---

## ☁️ Google Cloud Deployment Proof
- Deployed via **Google Cloud Build** to **Cloud Run**.
- Uses **GCP Secret Manager** for encrypted runtime access to keys.
- Demo Video: `google cloud run .mp4`
- API Proof: `gemini api Key proof.mp4`

---

## 📂 Project Structure
- `/app/api`: FastAPI routes (Public, Store, Chat).
- `/app/services`: Core logic (Orchestrator, Search, RAG Evaluator).
- `/app/tools`: Executable Shopify actions for the AI assistant.
- `/prisma`: Database schema and migrations.
