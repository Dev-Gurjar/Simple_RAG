# Construction RAG Chatbot — Backend

Multi-tenant RAG chatbot API for US construction companies.

## Stack

| Component | Service |
|-----------|---------|
| API Framework | FastAPI |
| Database | Supabase (Postgres) |
| Vector DB | Qdrant Cloud |
| Embeddings | Cohere embed-english-v3.0 |
| LLM | Groq (Llama 3.1 70B) |
| Doc Parsing | Docling on Kaggle GPU |
| Deployment | Render (Docker) |

## Quick Start

```bash
# 1. Clone & enter
cd backend

# 2. Create virtual env
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Mac/Linux

# 3. Install deps
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
# Fill in your API keys in .env

# 5. Run
uvicorn app.main:app --reload --port 8000
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) for interactive API docs.

## Project Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Settings from env vars
│   ├── api/
│   │   ├── auth.py          # Register / Login (JWT)
│   │   ├── documents.py     # Upload & manage PDFs
│   │   ├── chat.py          # RAG query endpoint
│   │   └── admin.py         # Tenant & stats
│   ├── services/
│   │   ├── docling_client.py    # Kaggle Docling parser
│   │   ├── embedding_service.py # Cohere embeddings
│   │   ├── qdrant_service.py    # Vector CRUD
│   │   ├── llm_service.py       # Groq LLM
│   │   └── rag_service.py       # Full RAG pipeline
│   ├── models/
│   │   └── schemas.py       # Pydantic models
│   └── db/
│       └── supabase.py      # Supabase client
├── requirements.txt
├── Dockerfile
└── render.yaml
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Create tenant + admin user |
| POST | `/auth/login` | Get JWT token |
| POST | `/documents/upload` | Upload PDF → parse → embed → store |
| GET | `/documents` | List tenant's documents |
| DELETE | `/documents/{id}` | Delete document + vectors |
| POST | `/chat` | RAG query |
| GET | `/chat/conversations` | List conversations |
| GET | `/chat/conversations/{id}` | Get conversation messages |
| GET | `/admin/tenant` | Tenant info |
| GET | `/admin/stats` | Usage statistics |

## Supabase Tables

Run this SQL in the Supabase SQL editor to create the schema:

```sql
-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Tenants
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'member',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Documents
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    chunk_count INT DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Conversations
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Messages
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Row Level Security
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

-- Indexes
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_tenant ON users(tenant_id);
CREATE INDEX idx_documents_tenant ON documents(tenant_id);
CREATE INDEX idx_conversations_tenant_user ON conversations(tenant_id, user_id);
CREATE INDEX idx_messages_conversation ON messages(conversation_id);
```

## Deploy to Render

1. Push to GitHub
2. On Render → New Web Service → Connect repo
3. Root Directory: `backend`
4. Environment: Docker
5. Add env vars from `.env.example`
6. Deploy

## Environment Variables

See [.env.example](.env.example) for all required variables.
