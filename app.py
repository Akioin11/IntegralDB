import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv, find_dotenv
from pathlib import Path
import os
import json

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

def get_search_term(query_text: str):
    """Uses the LLM to extract the key product/supplier from the query."""
    print(f"Extracting search term from: {query_text}")
    
    prompt = f"""
    You are a search query optimizer.
    Your job is to extract the main product name, component, or supplier
    from the user's question.
    
    Respond with *only* the cleanest possible search term.
    
    Examples:
    User: "how much a waterbath costs?"
    Response: "waterbath"
    
    User: "what's the price for the '10-pin connector' from 'TechConnect'?"
    Response: "10-pin connector TechConnect"
    
    User: "show me suppliers for component Y"
    Response: "component Y"
    
    User: "do you have any 500ml beakers?"
    Response: "500ml beaker"
    
    ---
    
    User: "{query_text}"
    Response:
    """
    try:
        response = gemini_model.generate_content(prompt)
        search_term = response.text.strip().replace('"', '')
        print(f"Extracted search term: {search_term}")
        return search_term
    except Exception as e:
        print(f"Error extracting search term: {e}")
        return query_text # Fallback to the original query
    

# --- 2. DATA RETRIEVAL FUNCTIONS ---

def query_structured_data(query_text: str):
    """Queries the SQL tables for exact matches."""
    print(f"Querying SQL for: {query_text}")
    try:
        # We query both products and suppliers using a simple 'ilike' (case-insensitive)
        # and join them.
        product_response = supabase.table("products").select(
            "product_name, price, sku, product_specifications, suppliers(supplier_name, contact_email, contact_phone)"
        ).ilike("product_name", f"%{query_text}%").limit(3).execute()
        
        return product_response.data
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

st.title("🤖 Supplier Database Q&A")
st.caption("Ask me about product prices, specifications, or supplier details.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("questions go here'?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing question..."):
            # *** NEW STEP ***
            # 1. Extract the clean search term from the user's question
            search_term = get_search_term(prompt)
        
        with st.spinner(f"Searching for '{search_term}'..."):
            # 2. Get context using the *clean search term*
            sql_data = query_structured_data(search_term)
            vector_data = query_vector_store(search_term)
            
            # 3. Get the final answer using the *original question*
            #    (This lets the LLM see the full intent)
            response = get_llm_response(prompt, sql_data, vector_data)
            
            st.markdown(response)
    
    st.session_state.messages.append({"role": "assistant", "content": response})