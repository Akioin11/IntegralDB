# --- IMPORTS (at top of file) ---
import streamlit as st
import google.generativeai as genai  # Using the existing library with updated models
from supabase import create_client, Client
from dotenv import load_dotenv, find_dotenv
from pathlib import Path
import os
import json
from pydantic import BaseModel # <-- YOU MUST REMOVE 'Field' FROM HERE IF IT EXISTS
from typing import Optional

# --- FIXED PYDANTIC MODELS (NO 'Field') ---
# These MUST look EXACTLY like this:

class SqlSearch(BaseModel):
    """A tool for searching the structured product/supplier database."""
    product_name: Optional[str] = None
    supplier_name: Optional[str] = None

class VectorSearch(BaseModel):
    """A tool for searching unstructured PDFs for general context."""
    query: str # <-- No default, no Field

class SearchPlan(BaseModel):
    """The complete plan of action to answer the user's query."""
    sql_search: Optional[SqlSearch] = None
    vector_search: Optional[VectorSearch] = None

# --- 1. CONFIGURATION ---
# (The rest of your file can stay the same)
...


# --- 1. CONFIGURATION ---
_dotenv_path = find_dotenv(usecwd=True)
if _dotenv_path:
    load_dotenv(_dotenv_path)
else:
    _alt_env = Path(__file__).resolve().parent / ".env"
    if _alt_env.exists():
        load_dotenv(_alt_env)

def _get_env(name: str) -> str | None:
    val = os.environ.get(name)
    if val is None:
        return None
    return val.strip().strip('"').strip("'")

GOOGLE_API_KEY = _get_env("GOOGLE_API_KEY")
SUPABASE_URL = _get_env("SUPABASE_URL")
SUPABASE_KEY = _get_env("SUPABASE_KEY")

missing = [k for k, v in {
    "GOOGLE_API_KEY": GOOGLE_API_KEY,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
}.items() if not v]

if missing:
    st.error(
        "Missing required environment variables: " + ", ".join(missing)
    )
    st.stop()

# --- CONFIGURE ALL ONLINE CLIENTS ---
try:
    genai.configure(api_key=GOOGLE_API_KEY)
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Client for final answers - using the correct model name
    gemini_model = genai.GenerativeModel('gemini-2.5-flash')
    
    # Client for embedding
    embedding_model = "models/embedding-001"

    # Client for planning - using the correct model name with no special generation config
    # Just create the base model, we'll set function calling in the generate_content call
    plan_model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    # This should no longer error, but if it does, we stop.
    st.error(f"Error initializing API clients: {e}")
    st.stop()


# --- 1.A SEARCH PLANNER ---
# Store function declaration as a global variable for reuse
# Create a simplified schema without $defs
function_declaration = {
    "name": "search_plan",
    "description": "Create a search plan for the user query",
    "parameters": {
        "type": "object",
        "properties": {
            "sql_search": {
                "type": "object",
                "description": "Parameters for searching the SQL database",
                "properties": {
                    "product_name": {
                        "type": "string", 
                        "description": "Name of the product to search for. Extract the core product name without qualifiers. For example, if the user asks about 'waterbath price', use 'waterbath'. Be flexible with spaces and variations (e.g., 'water bath' vs 'waterbath')."
                    },
                    "supplier_name": {
                        "type": "string", 
                        "description": "Name of the supplier to search for"
                    }
                }
            },
            "vector_search": {
                "type": "object",
                "description": "Parameters for searching unstructured PDFs",
                "properties": {
                    "query": {
                        "type": "string", 
                        "description": "The query to search for in PDFs. Include the original search terms and any synonyms."
                    }
                },
                "required": ["query"]
            }
        }
    }
}

def list_available_models():
    """List all available Gemini models"""
    try:
        models = genai.list_models()
        print("\nAvailable Models:")
        for model in models:
            print(f"- {model.name}")
        return models
    except Exception as e:
        print(f"Error listing models: {e}")
        return []

def get_search_plan(query_text: str) -> Optional[SearchPlan]:
    """Uses the LLM to create a structured search plan."""
    if not plan_model:
        return None
    
    # List available models for debugging
    list_available_models()
        
    print(f"Generating search plan for: {query_text}")
    
    # Enhanced prompt for better query understanding
    prompt = f"""
    You are a query-planning agent. Analyze the user's question and create
    a plan to retrieve data from SQL (for specific products/suppliers)
    and/or a Vector DB (for general context).
    
    IMPORTANT: Be flexible with product names. Users might type variations like:
    - "water bath" vs "waterbath"
    - Different capitalizations
    - Slight spelling variations
    
    Extract the core product name and be inclusive in your search strategy.
    For example, if the query is about "price of waterbath", the product_name 
    should be just "waterbath" or variants like "water bath" to ensure good matches.

    User: "{query_text}"
    """
    
    try:
        # Create the tools configuration with the function declaration
        tools = [{
            "function_declarations": [function_declaration]
        }]
        
        # Generate content with proper tool configuration
        # Note: we're removing the generation_config and simplifying for better compatibility
        response = plan_model.generate_content(
            prompt,
            tools=tools,
            tool_config={"function_calling_config": {"mode": "auto"}}
        )
        
        # Extract the structured output from the function call response
        if (hasattr(response, 'candidates') and response.candidates 
            and hasattr(response.candidates[0], 'content') 
            and response.candidates[0].content.parts 
            and hasattr(response.candidates[0].content.parts[0], 'function_call')):
            
            function_call = response.candidates[0].content.parts[0].function_call
            if function_call.name == "search_plan":
                # Parse the function call arguments as our SearchPlan
                plan_args = function_call.args
                
                # Create the SQL search part if it exists
                sql_search_args = plan_args.get("sql_search", {})
                sql_search = None
                if sql_search_args:
                    sql_search = SqlSearch(
                        product_name=sql_search_args.get("product_name"),
                        supplier_name=sql_search_args.get("supplier_name")
                    )
                
                # Create the Vector search part if it exists
                vector_search_args = plan_args.get("vector_search", {})
                vector_search = None
                if vector_search_args and "query" in vector_search_args:
                    vector_search = VectorSearch(query=vector_search_args.get("query"))
                
                # Create the final search plan
                search_plan = SearchPlan(
                    sql_search=sql_search,
                    vector_search=vector_search
                )
                print(f"[Search Plan]: {search_plan}")
                return search_plan
            else:
                print(f"Unexpected function call: {function_call.name}")
                return None
        else:
            print(f"No function call in response: {response}")
            return None
            
    except Exception as e:
        print(f"Error generating search plan: {e}")
        print(f"Response was: {response if 'response' in locals() else 'Not generated'}")
        return None

# --- 2. DATA RETRIEVAL FUNCTIONS ---

def query_structured_data(plan: SqlSearch):
    """Queries the SQL tables based on the structured plan."""
    if not plan: return []
    print(f"Querying SQL with plan: {plan}")
    try:
        query = supabase.table("products").select(
            "product_name, price, sku, product_specifications, suppliers(supplier_name, contact_email, contact_phone)"
        )
        
        if plan.product_name:
            # Extract and normalize the original search term
            original_term = plan.product_name
            
            # Create variations of the search term
            search_terms = [
                original_term,                         # Original term
                original_term.lower(),                 # Lowercase
                original_term.replace(" ", ""),        # No spaces
                original_term.replace(" ", "-"),       # Hyphenated
                original_term.replace("-", " "),       # Spaces instead of hyphens
                "".join(original_term.split()),        # All spaces removed
            ]
            
            # Add common variants for waterbath/water bath
            if "water" in original_term.lower() and "bath" in original_term.lower():
                search_terms.extend(["water bath", "waterbath", "Water Bath", "WaterBath"])
            
            # Remove duplicates while preserving order
            search_terms = list(dict.fromkeys(search_terms))
            print(f"Searching for product terms: {search_terms}")
            
            # Use multiple OR conditions for search terms
            for i, term in enumerate(search_terms):
                if i == 0:
                    # First term uses the regular ilike
                    query = query.ilike("product_name", f"%{term}%")
                else:
                    # Subsequent terms use or_
                    query = query.or_(f"product_name.ilike.%{term}%")
            
        if plan.supplier_name:
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
        # Create an embedding model
        embedding_model_client = genai.EmbeddingModel(embedding_model)
        
        # Get embeddings
        result = embedding_model_client.embed_content(
            content=query_text,
            task_type="RETRIEVAL_QUERY"
        )
        query_embedding = result.embedding
        
        matches = supabase.rpc('match_documents', {
            'query_embedding': query_embedding,
            'match_threshold': 0.1, # Lower threshold for more flexibility
            'match_count': 5        # Retrieve more potential matches
        }).execute()
        
        return matches.data
    except Exception as e:
        print(f"Error querying Vector DB: {e}")
        return []

# --- 3. RAG PROMPT & LLM CALL ---

def get_llm_response(query_text, sql_context, vector_context):
    """Generates a final answer using all context."""
    
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

    prompt = f"""
    You are an expert procurement assistant. Your job is to answer questions
    about suppliers and products based *only* on the context provided.
    
    Do not make up information. If the answer is not in the context,
    say "I could not find that information in the database."
    
    IMPORTANT:
    - Products may appear in the database with slight variations in their names 
      (e.g., "Water Bath" vs "waterbath")
    - When discussing product names in your answers, use the exact product name 
      as it appears in the database for clarity
    - Match user's informal or variant product terms to the official names in the database
    
    --- CONTEXT ---
    {context}
    ---
    
    User Question: {query_text}
    
    Answer:
    """
    
    print("\n--- Sending to Gemini ---")
    
    try:
        response = gemini_model.generate_content(prompt)
        # Extract text from the response object
        if response.candidates and response.candidates[0].content.parts:
            return response.candidates[0].content.parts[0].text
        else:
            return "I couldn't generate a response."
    except Exception as e:
        print(f"Error generating content: {e}")
        return "Sorry, I encountered an error trying to answer your question."

# --- 4. STREAMLIT UI (FIXED NameError) ---

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
            plan = get_search_plan(prompt)
            sql_data = []
            vector_data = []
            
            # This is the fix for NameError:
            # We must define 'response' here in case 'plan' fails
            response = None 

        if not plan:
            response = "Sorry, I had trouble understanding that. Could you rephrase?"
            st.error(response)
        else:
            with st.spinner("Searching database and documents..."):
                if plan.sql_search:
                    sql_data = query_structured_data(plan.sql_search)
                if plan.vector_search:
                    vector_data = query_vector_store(plan.vector_search.query)
                
                response = get_llm_response(prompt, sql_data, vector_data)
                st.markdown(response)
    
    # This block is now safe, because 'response' is guaranteed
    # to be defined (either with an answer or an error message).
    if response:
        st.session_state.messages.append({"role": "assistant", "content": response})