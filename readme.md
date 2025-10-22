# IntegralDB

IntegralDB is a comprehensive supplier and product information management system that integrates structured SQL database storage with vector-based document search capabilities. The system leverages Google's Gemini AI APIs for data extraction, embedding generation, and intelligent query processing.

## Architecture

The system is organized into a three-stage ETL (Extract, Transform, Load) pipeline, followed by a retrieval-augmented generation (RAG) query interface:

### 1. Data Ingestion (Day1_ingest.py)

- Authenticates with Gmail and Google Drive APIs using OAuth2
- Fetches supplier emails and attached PDF documents
- Saves a structured record of emails and downloads attachments locally
- Outputs `supplier_emails.csv` for downstream processing

### 2. Structured Data Extraction (Day2_process.py)

- Processes the emails and PDF attachments
- Uses Google Gemini 2.5 Flash with a Pydantic schema to extract:
  - Supplier information (name, contact details)
  - Product data (name, price, SKU, specifications)
- Stores structured data in PostgreSQL (via Supabase)
  - `suppliers` table for vendor information
  - `products` table with foreign key relationships to suppliers

### 3. Document Embedding (day3_embed.py)

- Processes PDF documents using pdfplumber
- Chunks text with controlled overlap for optimal semantic retrieval
- Generates embeddings using Google's text-embedding-004 model
- Stores document chunks with embeddings in a vector-enabled Postgres table

### 4. Query Interface (app.py)

- Streamlit web application providing a natural language interface
- Implements hybrid search combining:
  - Structured SQL queries for exact product/supplier matches
  - Vector similarity search for semantic document retrieval
- RAG-based response generation providing accurate, sourced answers

## Key Technologies

- **Google Gemini AI**: LLM-based structured data extraction and response generation
- **Supabase PostgreSQL**: Database with pgvector extension for vector storage/retrieval
- **Python Ecosystem**: 
  - pdfplumber for document text extraction
  - Pydantic for schema validation
  - Streamlit for the web interface
- **Gmail/Drive APIs**: Source data integration

## Environment Setup

The application requires the following environment variables:

```
GOOGLE_API_KEY=your_gemini_api_key
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_anon_key
```

Store these in a `.env` file in the project root directory.

## Getting Started

1. Create Google API credentials:
   - Generate `credentials.json` for Gmail/Drive access
   - Obtain a Gemini API key

2. Set up Supabase:
   - Create a new Supabase project
   - Enable pgvector extension
   - Create tables: `suppliers`, `products`, `documents`
   - Create the `match_documents` stored procedure

3. Run the pipeline:
   ```
   python Day1_ingest.py    # Collect data
   python Day2_process.py   # Extract structured data
   python day3_embed.py     # Create document embeddings
   ```

4. Launch the query interface:
   ```
   streamlit run app.py
   ```

## Repository Structure

- `app.py`: Streamlit application with RAG-based query interface
- `Day1_ingest.py`: Email/attachment ingestion from Gmail
- `Day2_process.py`: LLM-based structured data extraction
- `day3_embed.py`: Document chunking and embedding generation
- `credentials.json`: Google API credentials file
- `token.json`: OAuth2 token storage (auto-generated)
- `supplier_emails.csv`: Intermediate data file
- `attachments/`: Directory for PDF document storage
- `apis/`: Helper modules for API interactions
- `.env`: Environment variables (not tracked in git)

## License

Proprietary - All Rights Reserved
