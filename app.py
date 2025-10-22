import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv, find_dotenv
from pathlib import Path
import os
import json
from pydantic import BaseModel, Field
from typing import Optional

class SqlSearch(BaseModel):
    """A tool for searching the structured product/supplier database."""
    product_name: Optional[str] = Field(None, description="The specific product name to filter on.")
    supplier_name: Optional[str] = Field(None, description="The specific supplier name to filter on.")

class VectorSearch(BaseModel):
    """A tool for searching unstructured PDFs for general context."""
    query: str = Field(..., description="The semantic query for vector search.")

class SearchPlan(BaseModel):
    """The complete plan of action to answer the user's query."""
    sql_search: Optional[SqlSearch] = Field(None, description="The plan for structured SQL search.")
    vector_search: Optional[VectorSearch] = Field(None, description="The plan for unstructured vector search.")


# --- 1. CONFIGURATION ---
# Load .env robustly regardless of where Streamlit is launched from
_dotenv_path = find_dotenv(usecwd=True)
if _dotenv_path:
    load_dotenv(_dotenv_path)
else:
    # Fallback: look next to this file
    _alt_env = Path(__file__).resolve().parent / ".env"
    if _alt_env.exists():
        load_dotenv(_alt_env)

def _get_env(name: str) -> str | None:
    val = os.environ.get(name)
    if val is None:
        return None
    # Strip surrounding quotes/whitespace just in case
    return val.strip().strip('"').strip("'")

GOOGLE_API_KEY = _get_env("GOOGLE_API_KEY")
SUPABASE_URL = _get_env("SUPABASE_URL")
SUPABASE_KEY = _get_env("SUPABASE_KEY")

# Validate required configuration before creating clients
missing = [k for k, v in {
    "GOOGLE_API_KEY": GOOGLE_API_KEY,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
}.items() if not v]

if missing:
    st.error(
        "Missing required environment variables: " + ", ".join(missing) +
        "\nCreate a .env file in the project root with these keys, or set them in your environment."
    )
    st.stop()

# Configure clients
genai.configure(api_key=GOOGLE_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
gemini_model = genai.GenerativeModel('gemini-2.5-flash')
embedding_model = "models/text-embedding-004"

# --- 1.A NEW FUNCTION: KEYWORD EXTRACTOR ---

# In app.py, replace your old get_search_term function with this:

# 1. Re-configure the Gemini model to use Pydantic
try:
    plan_generation_config = genai.GenerationConfig(
        response_mime_type="application/json",
        response_schema=SearchPlan  # <-- Use our new Pydantic plan
    )
    plan_model = genai.GenerativeModel(
        'gemini-1.5-flash',
        generation_config=plan_generation_config
    )
except Exception as e:
    print(f"Error setting up planning model: {e}")
    # Fallback or error
    plan_model = None

def get_search_plan(query_text: str) -> Optional[SearchPlan]:
    """Uses the LLM to create a structured search plan."""
    if not plan_model:
        return None
        
    print(f"Generating search plan for: {query_text}")
    
    prompt = f"""
    You are a query-planning agent. Your job is to analyze the user's
    question and create a plan to retrieve data from two sources:
    
    1.  A SQL database (for exact product/supplier info).
    2.  A Vector database (for general context from PDFs).

    Plan:
    - If the user asks for a specific product, price, or supplier,
      use `SqlSearch`.
    - If the user asks a general question, for specifications, or
      "about" something, use `VectorSearch`.
    - You can use *both* tools if needed.

    Examples:
    User: "what's the price for the '10-pin connector' from 'TechConnect'?"
    Plan:
      "sql_search": {{"product_name": "10-pin connector", "supplier_name": "TechConnect"}},
      "vector_search": {{"query": "price for 10-pin connector from TechConnect"}}
      
    User: "how much does a waterbath cost?"
    Plan:
      "sql_search": {{"product_name": "waterbath"}},
      "vector_search": {{"query": "waterbath specifications and pricing"}}
      
    User: "tell me about fume hoods"
    Plan:
      "vector_search": {{"query": "fume hood features and suppliers"}}
      
    User: "do you have anything from 'Global Labs Inc'?"
    Plan:
      "sql_search": {{"supplier_name": "Global Labs Inc"}}
    ---
    
    User: "{query_text}"
    """
    
    try:
        response = plan_model.generate_content(prompt)
        plan_data = json.loads(response.text)
        search_plan = SearchPlan(**plan_data)
        
        print(f"[Search Plan]: {search_plan}")
        return search_plan
        
    except Exception as e:
        print(f"Error generating search plan: {e}")
        return None

# --- 2. DATA RETRIEVAL FUNCTIONS ---

# In app.py, replace your old query_structured_data function with this:

def query_structured_data(plan: SqlSearch):
    """Queries the SQL tables based on the structured plan."""
    if not plan:
        return []
        
    print(f"Querying SQL with plan: {plan}")
    try:
        # Start building the query
        query = supabase.table("products").select(
            "product_name, price, sku, product_specifications, suppliers(supplier_name, contact_email, contact_phone)"
        )
        
        # Conditionally add filters
        if plan.product_name:
            query = query.ilike("product_name", f"%{plan.product_name}%")
            
        if plan.supplier_name:
            # We need to filter on the joined 'suppliers' table
            query = query.ilike("suppliers.supplier_name", f"%{plan.supplier_name}%")
            
        response = query.limit(5).execute()
        return response.data
        
    except Exception as e:
        print(f"Error querying SQL: {e}")
        return []

def query_vector_store(query_text: str):
    """Queries the vector store for semantic matches."""
    print(f"Querying Vector DB for: {query_text}")
    try:
        # 1. Create embedding for the user's query
        query_embedding = genai.embed_content(
            model=embedding_model,
            content=query_text,
            task_type="RETRIEVAL_QUERY"
        )['embedding']
        
        # 2. Call the 'match_documents' SQL function we created
        matches = supabase.rpc('match_documents', {
            'query_embedding': query_embedding,
            'match_threshold': 0.3, # Adjust this threshold as needed
            'match_count': 3
        }).execute()
        
        return matches.data
    except Exception as e:
        print(f"Error querying Vector DB: {e}")
        return []

# --- 3. RAG PROMPT & LLM CALL ---

def get_llm_response(query_text, sql_context, vector_context):
    """Generates a final answer using all context."""
    
    # Format the context
    context = "--- SQL Database Context (Prices, SKUs, Suppliers) ---\n"
    if sql_context:
        context += json.dumps(sql_context, indent=2)
    else:
        context += "No exact matches found in the product database."
    
    context += "\n\n--- PDF Document Context (General info, specs, catalogs) ---\n"
    if vector_context:
        for item in vector_context:
            context += f"Source: {item['source_filename']}\nSnippet: {item['content']}\n\n"
    else:
        context += "No relevant information found in PDF documents."

    # Create the final prompt
    prompt = f"""
    You are an expert procurement assistant. Your job is to answer questions
    about suppliers and products based *only* on the context provided.
    
    Do not make up information. If the answer is not in the context,
    say "I could not find that information in the database."
    
    --- CONTEXT ---
    {context}
    ---
    
    User Question: {query_text}
    
    Answer:
    """
    
    print("\n--- Sending to Gemini ---")
    print(prompt)
    
    try:
        response = gemini_model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Error generating content: {e}")
        return "Sorry, I encountered an error trying to answer your question."

# --- 4. STREAMLIT UI (UPDATED LOGIC) ---

# In app.py, replace the final Streamlit UI block with this:

st.title("🤖 Supplier Database Q&A")
st.caption("Ask me about product prices, specifications, or supplier details.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("What is the price for the '10-pin connector'?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing question..."):
            # 1. Get the structured search plan
            plan = get_search_plan(prompt)
            sql_data = []
            vector_data = []

        if not plan:
            st.error("Sorry, I had trouble understanding that. Could you rephrase?")
        else:
            with st.spinner("Searching database and documents..."):
                # 2. Execute the plan
                if plan.sql_search:
                    sql_data = query_structured_data(plan.sql_search)
                if plan.vector_search:
                    vector_data = query_vector_store(plan.vector_search.query)
                
                # 3. Get the final answer
                response = get_llm_response(prompt, sql_data, vector_data)
                st.markdown(response)
    
    st.session_state.messages.append({"role": "assistant", "content": response})