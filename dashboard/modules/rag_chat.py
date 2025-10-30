"""RAG Chat module ported from the existing top-level app.py.

Expose TITLE and app() for the dashboard to load.
"""
from typing import Optional, Tuple, List
import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
import google.generativeai as genai
from supabase import create_client, Client
import streamlit as st


TITLE = "RAG Chat"


def _get_env(name: str) -> Optional[str]:
    val = os.environ.get(name)
    if val is None:
        return None
    return val.strip().strip('"').strip("'")


def _load_env():
    _dotenv_path = find_dotenv(usecwd=True)
    if _dotenv_path:
        load_dotenv(_dotenv_path)
    else:
        _alt_env = Path(__file__).resolve().parent.parent / ".env"
        if _alt_env.exists():
            load_dotenv(_alt_env)
        elif (Path.cwd() / ".env").exists():
            load_dotenv(Path.cwd() / ".env")


def initialize_clients():
    _load_env()
    GOOGLE_API_KEY = _get_env("GOOGLE_API_KEY")
    SUPABASE_URL = _get_env("SUPABASE_URL")
    SUPABASE_KEY = _get_env("SUPABASE_KEY")

    missing = [k for k, v in {
        "GOOGLE_API_KEY": GOOGLE_API_KEY,
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_KEY": SUPABASE_KEY,
    }.items() if not v]

    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    genai.configure(api_key=GOOGLE_API_KEY)
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    embedding_model = "models/text-embedding-004"
    generative_model = genai.GenerativeModel('gemini-2.5-flash')

    return supabase, embedding_model, generative_model


def get_query_embedding(text: str, model: str) -> Optional[list]:
    try:
        result = genai.embed_content(
            model=model,
            content=text,
            task_type="RETRIEVAL_QUERY"
        )
        return result['embedding']
    except Exception:
        return None


def find_relevant_documents(supabase_client: Client, embedding: list, match_threshold=0.4, match_count=5) -> list:
    try:
        response = supabase_client.rpc('match_documents', {
            'query_embedding': embedding,
            'match_threshold': match_threshold,
            'match_count': match_count
        }).execute()
        return response.data
    except Exception:
        return []


def get_generative_answer(model: genai.GenerativeModel, query: str, context_chunks: list) -> Tuple[str, bool]:
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
        formatted_context = "\n\n---\n\n".join(
            [f"Source: {chunk.get('source_filename')}\nContent: {chunk.get('content')}" for chunk in context_chunks]
        )
        prompt = f"""
        You are an expert assistant for a supplier database.
        Use the following pieces of context from supplier documents to answer the user's question.
        If the answer isn't in the context, say you don't know. Do not make up information.
        Reply with general knowledge if context/data not available
        CONTEXT:
        {formatted_context}

        USER QUESTION:
        {query}

        ANSWER:
        """

    try:
        response = model.generate_content(prompt)
        return response.text, context_found
    except Exception:
        return "Sorry, I encountered an error while generating the answer.", False


def app():
    st.header(TITLE)
    try:
        supabase, embedding_model, generative_model = initialize_clients()
    except Exception as e:
        st.error(str(e))
        st.info("Create a .env file with GOOGLE_API_KEY, SUPABASE_URL, SUPABASE_KEY or set them in your environment.")
        return

    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "Hi! Ask me anything about your database."}
        ]

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"]) 

    if query := st.chat_input("Ask a question about your suppliers, pricing, or documents."):
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        with st.chat_message("assistant"):
            with st.spinner("Searching and thinking..."):
                query_embedding = get_query_embedding(query, embedding_model)
                documents = []
                context_found = False
                if query_embedding:
                    documents = find_relevant_documents(supabase, query_embedding)

                answer, context_found = get_generative_answer(generative_model, query, documents)
                st.markdown(answer)

                if context_found and documents:
                    with st.expander("Show Sources"):
                        for doc in documents:
                            st.markdown(f"**Source:** `{doc.get('source_filename')}`")
                            st.markdown(f"**Similarity:** {doc.get('similarity', 0):.4f}")
                            st.caption(f"{doc.get('content','')[:300]}...")

                st.session_state.messages.append({"role": "assistant", "content": answer})
