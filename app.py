# app.py
import os
import streamlit as st
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv, find_dotenv
from pathlib import Path
from typing import Optional, Tuple, List, Any, Dict

# -------------------------
# CONFIG / SECRETS (Streamlit secrets preferred)
# -------------------------
# Load local .env when developing locally (keeps parity)
_dotenv_path = find_dotenv(usecwd=True)
if _dotenv_path:
    load_dotenv(_dotenv_path)
else:
    _alt_env = Path(__file__).resolve().parent / ".env"
    if _alt_env.exists():
        load_dotenv(_alt_env)
    elif (Path.cwd() / ".env").exists():
        load_dotenv(Path.cwd() / ".env")


def _get_secret(name: str) -> Optional[str]:
    """
    Prefer Streamlit secrets when available (Streamlit Cloud).
    Fall back to environment variables (.env) for local dev.
    """
    try:
        # st.secrets only exists in Streamlit runtime; safe to call
        val = st.secrets.get(name) if isinstance(st.secrets, dict) else None
        if val:
            return str(val).strip().strip('"').strip("'")
    except Exception:
        # Not running inside Streamlit or st.secrets not present
        pass

    val = os.getenv(name)
    if val is None:
        return None
    return val.strip().strip('"').strip("'")


GOOGLE_API_KEY = _get_secret("GOOGLE_API_KEY")
SUPABASE_URL = _get_secret("SUPABASE_URL")
# IMPORTANT: Use the anon key on the client/frontend (Streamlit). Do NOT put service_role here.
SUPABASE_KEY = _get_secret("SUPABASE_KEY")

missing = [k for k, v in {
    "GOOGLE_API_KEY": GOOGLE_API_KEY,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_ANON_KEY": SUPABASE_ANON_KEY,
}.items() if not v]

if missing:
    st.error("Missing required environment variables: " + ", ".join(missing))
    st.info("Add them to Streamlit secrets (or local .env for dev): GOOGLE_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY")
    st.stop()

# -------------------------
# INITIALIZE CLIENTS
# -------------------------
try:
    genai.configure(api_key=GOOGLE_API_KEY)

    # Use anon key for Streamlit frontend auth and normal queries (service_role not included)
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

    # Gemini models
    embedding_model = "models/text-embedding-004"
    generative_model = genai.GenerativeModel('gemini-2.5-flash')

except Exception as e:
    st.error(f"Error initializing clients: {e}")
    st.error("Please check your API keys and Supabase credentials.")
    st.stop()


# -------------------------
# RAG CORE FUNCTIONS
# -------------------------
def get_query_embedding(text: str, model: str) -> Optional[list]:
    try:
        result = genai.embed_content(
            model=model,
            content=text,
            task_type="RETRIEVAL_QUERY"
        )
        return result['embedding']
    except Exception as e:
        st.error(f"Error creating query embedding: {e}")
        return None


def find_relevant_documents(supabase_client: Client, embedding: list, match_threshold=0.4, match_count=5, user_id: Optional[str] = None) -> list:
    """
    Finds relevant document chunks from Supabase vector store.
    Optionally pass user_id for logging/scoping (depends on your RPC implementation).
    """
    try:
        params = {
            'query_embedding': embedding,
            'match_threshold': match_threshold,
            'match_count': match_count
        }
        if user_id:
            # If your RPC accepts user_id, it will be included; harmless otherwise if not used.
            params['user_id'] = user_id

        response = supabase_client.rpc('match_documents', params).execute()
        return response.data or []
    except Exception as e:
        st.error(f"Error searching Supabase: {e}")
        st.info(f"Supabase error: {e}")
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
    except Exception as e:
        st.error(f"Error generating answer: {e}")
        return "Sorry, I encountered an error while generating the answer.", False


# -------------------------
# AUTH HELPERS
# -------------------------
def is_logged_in() -> bool:
    return st.session_state.get("supabase_user") is not None


def _store_session(res: Any) -> bool:
    """
    Normalize the supabase-py response and store session info in st.session_state.
    Returns True on success.
    Handles multiple possible return shapes across supabase client versions.
    """
    user: Optional[Dict] = None
    access_token: Optional[str] = None

    if isinstance(res, dict):
        # common new shape: {'user':..., 'session':...}
        if res.get("user"):
            user = res.get("user")
        # older shape: {'data': {'user':..., 'session':...}}
        if not user and res.get("data") and isinstance(res["data"], dict):
            user = res["data"].get("user") or res["data"].get("session", {}).get("user")
        # token forms
        if res.get("access_token"):
            access_token = res.get("access_token")
        elif res.get("session") and isinstance(res["session"], dict):
            access_token = res["session"].get("access_token")
        elif res.get("data") and isinstance(res["data"], dict) and res["data"].get("session"):
            access_token = res["data"]["session"].get("access_token")

    if not user:
        return False

    st.session_state["supabase_user"] = user
    if access_token:
        st.session_state["access_token"] = access_token
    return True


def login_form():
    st.subheader("Sign in")
    email = st.text_input("Email", key="login_email")
    password = st.text_input("Password", type="password", key="login_pass")
    if st.button("Sign in"):
        try:
            res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        except Exception as e:
            st.error(f"Login call failed: {e}")
            return False

        ok = _store_session(res)
        if not ok:
            # show raw response for debug; remove in production if noisy
            st.error("Login failed. Response: " + str(res))
            return False
        st.experimental_rerun()


def signup_form():
    st.subheader("Create account")
    email = st.text_input("Email (signup)", key="su_email")
    password = st.text_input("Password (signup)", type="password", key="su_pass")
    if st.button("Sign up"):
        try:
            res = supabase.auth.sign_up({"email": email, "password": password})
        except Exception as e:
            st.error(f"Signup call failed: {e}")
            return False
        st.info("If sign-up succeeded, check your email to confirm (if confirmations enabled). Try signing in.")
        return True


def logout():
    # Client-side cleanup. No service_role used here.
    st.session_state.pop("supabase_user", None)
    st.session_state.pop("access_token", None)
    st.experimental_rerun()


# -------------------------
# STREAMLIT UI (with auth gating)
# -------------------------
def main():
    st.set_page_config(page_title="IntegralDB (Authenticated)", layout="wide")
    st.title("Integral Internal Database")

    # Sidebar auth UI
    with st.sidebar:
        if not is_logged_in():
            login_form()
            st.markdown("---")
            signup_form()
            st.caption("Using Supabase Auth (anon key). Admin/service_role keys must NOT be in this app.")
            # Block the rest of the UI until user logs in
            st.stop()
        else:
            user = st.session_state["supabase_user"]
            # user object shape may vary; attempt to show email
            user_email = user.get("email") or (user.get("user_metadata") or {}).get("email") or user.get("aud") or user.get("id")
            st.write(f"Signed in: {user_email}")
            if st.button("Logout"):
                logout()

    # Authenticated from here on
    user = st.session_state["supabase_user"]
    user_id = user.get("id") or user.get("sub")  # pick what exists

    # Initialize chat
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "Hi! Ask me anything about your database."}
        ]

    # Show past messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # New query input
    if query := st.chat_input("Mention all details that are needed here."):
        # append user message
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        # assistant response
        with st.chat_message("assistant"):
            with st.spinner("Searching and thinking..."):
                # 1. Create query embedding
                query_embedding = get_query_embedding(query, embedding_model)
                documents = []
                context_found = False

                if query_embedding:
                    # 2. Find relevant documents (pass user_id optionally for logging/RLS)
                    documents = find_relevant_documents(supabase, query_embedding, user_id=user_id)

                # 3. Generate answer
                answer, context_found = get_generative_answer(generative_model, query, documents)

                # 4. Display the answer
                st.markdown(answer)

                # 5. Show sources if used
                if context_found and documents:
                    with st.expander("Show Sources"):
                        for doc in documents:
                            st.markdown(f"**Source:** `{doc.get('source_filename')}`")
                            st.markdown(f"**Similarity:** {doc.get('similarity'):.4f}")
                            st.caption(f"{doc.get('content')[:300]}...")

                st.session_state.messages.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    main()
