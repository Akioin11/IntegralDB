import os
import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv, find_dotenv
from typing import Optional, Tuple

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="IntegralDB", layout="wide")

# Robust Secret Management for Streamlit Cloud vs Local
def get_secret(key: str) -> Optional[str]:
    # 1. Check Streamlit Secrets (Cloud Deployment standard)
    if key in st.secrets:
        return st.secrets[key]
    # 2. Check OS Environment (Docker/System)
    if key in os.environ:
        return os.environ[key]
    # 3. Fallback to .env (Local Dev)
    load_dotenv(find_dotenv())
    return os.environ.get(key)

GOOGLE_API_KEY = get_secret("GOOGLE_API_KEY")
SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")

if not all([GOOGLE_API_KEY, SUPABASE_URL, SUPABASE_KEY]):
    st.error("Missing required secrets. Set GOOGLE_API_KEY, SUPABASE_URL, and SUPABASE_KEY in st.secrets or .env.")
    st.stop()

# --- 2. INITIALIZE CLIENTS (Cached) ---
# @st.cache_resource ensures these run once, not every time the user types a message.
@st.cache_resource
def init_clients():
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        sb_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        e_model = "models/text-embedding-004"
        g_model = genai.GenerativeModel('gemini-2.5-flash')
        return sb_client, e_model, g_model
    except Exception as e:
        st.error(f"Critical Error: {e}")
        st.stop()

supabase, embedding_model, generative_model = init_clients()

# --- 3. RAG CORE FUNCTIONS ---

def get_query_embedding(text: str) -> Optional[list]:
    try:
        result = genai.embed_content(
            model=embedding_model,
            content=text,
            task_type="RETRIEVAL_QUERY"
        )
        return result['embedding']
    except Exception as e:
        st.error(f"Embedding Error: {e}")
        return None

def find_relevant_documents(embedding: list, match_threshold=0.4, match_count=5) -> list:
    try:
        response = supabase.rpc('match_documents', {
            'query_embedding': embedding,
            'match_threshold': match_threshold,
            'match_count': match_count
        }).execute()
        return response.data
    except Exception as e:
        st.error(f"Database Error: {e}")
        return []

def get_generative_answer(query: str, context_chunks: list) -> Tuple[str, bool]:
    if not context_chunks:
        prompt = f"""
        You are a helpful assistant. The user's specific query was not found in the database.
        Answer based on general knowledge, but explicitly state that this is NOT from the internal database.
        
        USER QUESTION: {query}
        """
        context_found = False
    else:
        context_found = True
        formatted_context = "\n\n".join(
            [f"Source: {chunk['source_filename']}\nContent: {chunk['content']}" for chunk in context_chunks]
        )
        prompt = f"""
        You are an expert assistant for the 'IntegralDB' supplier system.
        Answer the question using ONLY the context provided below.
        If the answer is not in the context, say "I don't have that information in the database."
        
        CONTEXT:
        {formatted_context}

        USER QUESTION: {query}
        """
    
    try:
        response = generative_model.generate_content(prompt)
        return response.text, context_found
    except Exception as e:
        return "I encountered an error generating the response.", False

# --- 4. MAIN UI ---

def main():
    st.title("Integral Internal Database")
    
    # Sidebar for controls
    with st.sidebar:
        st.header("Controls")
        if st.button("Clear Chat History", type="primary"):
            st.session_state.messages = []
            st.rerun()

    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "System Ready. Query the supplier database."}
        ]

    # Display chat
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Handle Input
    if query := st.chat_input("Ask about suppliers, parts, or contracts..."):
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        with st.chat_message("assistant"):
            with st.spinner("Processing..."):
                # 1. Embed
                q_embedding = get_query_embedding(query)
                
                # 2. Retrieve
                documents = []
                if q_embedding:
                    documents = find_relevant_documents(q_embedding)
                
                # 3. Generate
                answer, context_found = get_generative_answer(query, documents)
                
                st.markdown(answer)
                
                # 4. Sources Expander
                if context_found and documents:
                    with st.expander("View Retrieved Sources"):
                        for doc in documents:
                            st.markdown(f"**{doc.get('source_filename', 'Unknown Source')}** (Sim: {doc.get('similarity', 0):.2f})")
                            st.caption(doc.get('content', '')[:200] + "...")
                
                st.session_state.messages.append({"role": "assistant", "content": answer})

if __name__ == "__main__":
    main()