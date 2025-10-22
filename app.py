import os
import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv, find_dotenv
from pathlib import Path
from typing import Optional, Tuple, List

# --- 1. CONFIGURATION (Unchanged) ---
_dotenv_path = find_dotenv(usecwd=True)
if _dotenv_path:
    load_dotenv(_dotenv_path)
else:
    _alt_env = Path(__file__).resolve().parent / ".env"
    if _alt_env.exists():
        load_dotenv(_alt_env)
    # Fallback for environments where __file__ isn't defined
    elif (Path.cwd() / ".env").exists():
         load_dotenv(Path.cwd() / ".env")


def _get_env(name: str) -> Optional[str]:
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
    st.info("Please create a .env file in the root directory with the required keys.")
    st.stop()

# --- 2. INITIALIZE CLIENTS (Unchanged) ---
try:
    genai.configure(api_key=GOOGLE_API_KEY)
    
    # Initialize Supabase client
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Initialize Gemini models
    embedding_model = "models/text-embedding-004"
    generative_model = genai.GenerativeModel('gemini-2.5-flash')
    
except Exception as e:
    st.error(f"Error initializing clients: {e}")
    st.error("Please check your API keys and Supabase credentials.")
    st.stop()


# --- 3. RAG CORE FUNCTIONS (One function modified) ---

def get_query_embedding(text: str, model: str) -> Optional[list]:
    """Generates an embedding for the user's query."""
    try:
        result = genai.embed_content(
            model=model,
            content=text,
            task_type="RETRIEVAL_QUERY" # Use 'RETRIEVAL_QUERY' for queries
        )
        return result['embedding']
    except Exception as e:
        st.error(f"Error creating query embedding: {e}")
        return None

def find_relevant_documents(supabase_client: Client, embedding: list, match_threshold=0.4, match_count=5) -> list:
    """Finds relevant document chunks from Supabase vector store."""
    try:
        # This RPC call correctly maps to your fixed SQL function
        response = supabase_client.rpc('match_documents', {
            'query_embedding': embedding,
            'match_threshold': match_threshold,
            'match_count': match_count
        }).execute()
        
        return response.data
    except Exception as e:
        st.error(f"Error searching Supabase: {e}")
        st.info(f"Supabase error: {e}")
        return []

# *** MODIFIED FUNCTION ***
# Removed `st.warning` to make it a pure function.
# It now returns the answer and a boolean indicating if context was found.
def get_generative_answer(model: genai.GenerativeModel, query: str, context_chunks: list) -> Tuple[str, bool]:
    """Generates a final answer using the query and retrieved context."""
    
    if not context_chunks:
        context_found = False
        prompt = f"""
        You are a helpful general assistant. The user's question could not be
        found in the database. Answer the user's question from your
        general knowledge.
        
        USER QUESTION:
        {query}

        ANSWER:
        """
    else:
        context_found = True
        # Format the context for the prompt
        formatted_context = "\n\n---\n\n".join(
            [f"Source: {chunk['source_filename']}\nContent: {chunk['content']}" for chunk in context_chunks]
        )
        
        prompt = f"""
        You are an expert assistant for a supplier database.
        Use the following pieces of context from supplier documents to answer the user's question.
        If the answer isn't in the context, say you don't know. Do not make up information.

        CONTEXT:
        {formatted_context}

        USER QUESTION:
        {query}

        ANSWER:
        """
    
    try:
        response = model.generate_content(prompt)
        return response.text, context_found
    except Exception as e:
        st.error(f"Error generating answer: {e}")
        return "Sorry, I encountered an error while generating the answer.", False

# --- 4. STREAMLIT UI (Completely replaced with chat logic) ---

def main():
    st.set_page_config(page_title="IntegralDB", layout="wide")
    st.title("Integral Internal Database")
    
    # 1. Initialize chat history in session state
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "Hi! Ask me anything about your database."}
        ]

    # 2. Display all past messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # 3. Get new user query using st.chat_input
    if query := st.chat_input("Mention all details that are needed here."):
        
        # 4. Add and display the user's query
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        # 5. Generate and display the assistant's response
        with st.chat_message("assistant"):
            with st.spinner("Searching and thinking..."):
                
                # --- This is the full RAG pipeline from your old `main` ---
                
                # 1. Create query embedding
                query_embedding = get_query_embedding(query, embedding_model)
                
                documents = []
                context_found = False
                
                if query_embedding:
                    # 2. Find relevant documents
                    documents = find_relevant_documents(supabase, query_embedding)
                
                # 3. Generate answer
                answer, context_found = get_generative_answer(generative_model, query, documents)
                
                # 4. Display the answer
                st.markdown(answer)
                
                # 5. (Optional) Show sources if they were used
                if context_found and documents:
                    with st.expander("Show Sources"):
                        for doc in documents:
                            st.markdown(f"**Source:** `{doc['source_filename']}`")
                            st.markdown(f"**Similarity:** {doc['similarity']:.4f}")
                            st.caption(f"{doc['content'][:300]}...")
                
                # 6. Add the text answer to session state
                st.session_state.messages.append({"role": "assistant", "content": answer})

if __name__ == "__main__":
    main()