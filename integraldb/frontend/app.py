from pathlib import Path
from typing import Optional, List
import logging
from supabase import create_client, Client
import google.generativeai as genai
import streamlit as st
from .config import config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize clients
try:
    genai.configure(api_key=config.GOOGLE_API_KEY)
    supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    generative_model = genai.GenerativeModel(config.GENERATIVE_MODEL)
except Exception as e:
    logger.error(f"Error initializing clients: {e}")
    raise

def get_query_embedding(text: str) -> Optional[List[float]]:
    """Generate embedding for search query"""
    try:
        result = genai.embed_content(
            model=config.EMBEDDING_MODEL,
            content=text,
            task_type="RETRIEVAL_QUERY"
        )
        return result['embedding']
    except Exception as e:
        logger.error(f"Error creating query embedding: {e}")
        return None

def find_relevant_documents(embedding: List[float]) -> List[dict]:
    """Find relevant documents using vector similarity"""
    try:
        response = supabase.rpc('match_documents', {
            'query_embedding': embedding,
            'match_threshold': config.MATCH_THRESHOLD,
            'match_count': config.MATCH_COUNT
        }).execute()
        return response.data
    except Exception as e:
        logger.error(f"Error searching Supabase: {e}")
        return []

def get_answer(query: str, context_chunks: List[dict]) -> tuple[str, bool]:
    """Generate answer using RAG"""
    if not context_chunks:
        prompt = f"""
        You are a helpful general assistant. The user's question could not be
        found in the database. Answer the user's question from your
        general knowledge.
        
        USER QUESTION:
        {query}

        ANSWER:
        """
        context_found = False
    else:
        formatted_context = "\n\n---\n\n".join(
            [f"Source: {chunk['source_filename']}\nContent: {chunk['content']}"
             for chunk in context_chunks]
        )
        
        prompt = f"""
        You are an expert assistant for a supplier database.
        Use the following pieces of context to answer the user's question.
        If the answer isn't in the context, say you don't know.
        
        CONTEXT:
        {formatted_context}

        USER QUESTION:
        {query}

        ANSWER:
        """
        context_found = True
    
    try:
        response = generative_model.generate_content(prompt)
        return response.text, context_found
    except Exception as e:
        logger.error(f"Error generating answer: {e}")
        return "Sorry, I encountered an error while generating the answer.", False

def main():
    """Main Streamlit application"""
    st.set_page_config(
        page_title=config.PAGE_TITLE,
        page_icon=config.PAGE_ICON,
        layout="wide"
    )
    st.title(config.PAGE_TITLE)
    
    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "Hi! Ask me anything about your database."}
        ]

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Get user input
    if query := st.chat_input("Ask a question about your documents..."):
        # Display user query
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        # Generate response
        with st.chat_message("assistant"):
            with st.spinner("Searching database..."):
                # 1. Create query embedding
                embedding = get_query_embedding(query)
                if not embedding:
                    st.error("Failed to process your query. Please try again.")
                    return

                # 2. Find relevant documents
                docs = find_relevant_documents(embedding)
                
                # 3. Generate answer
                answer, context_found = get_answer(query, docs)
                
                # 4. Display answer
                st.markdown(answer)
                
                # 5. Show context info
                if not context_found:
                    st.info("No relevant documents found. This answer is based on general knowledge.")
                elif st.checkbox("Show source documents"):
                    st.divider()
                    for doc in docs:
                        with st.expander(f"Source: {doc['source_filename']}"):
                            st.write(doc['content'])
                
                # Add response to chat history
                st.session_state.messages.append(
                    {"role": "assistant", "content": answer}
                )

if __name__ == "__main__":
    main()