import os
import pdfplumber
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv
import time

# --- 0. LOAD CONFIG ---
load_dotenv()
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

genai.configure(api_key=GOOGLE_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
print("Clients initialized.")

# --- 1. CHUNKING & PARSING ---

def parse_pdf(file_path):
    """Reads all text from a PDF file."""
    if not os.path.exists(file_path):
        return ""
    try:
        with pdfplumber.open(file_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += page.extract_text(x_tolerance=1) or ""
            return full_text
    except Exception as e:
        print(f"Error reading PDF {file_path}: {e}")
        return ""

def split_text(text, chunk_size=1000, chunk_overlap=200):
    """Splits text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += (chunk_size - chunk_overlap)
    return chunks

# --- 2. EMBEDDING ---

def get_embedding(text, model="models/text-embedding-004"):
    """Generates an embedding for a text chunk."""
    try:
        # NOTE: Gemini batches embeddings, but we'll do one at a time for simplicity
        result = genai.embed_content(model=model, content=text, task_type="RETRIEVAL_DOCUMENT")
        return result['embedding']
    except Exception as e:
        print(f"Error creating embedding: {e}")
        # Handle API rate limits by waiting
        if "rate limit" in str(e).lower():
            print("Rate limit hit, sleeping for 5 seconds...")
            time.sleep(5)
            return get_embedding(text, model) # Retry
        return None

# --- 3. MAIN INDEXING LOGIC ---

def main():
    attachment_dir = "attachments"
    if not os.path.exists(attachment_dir):
        print(f"Error: Directory '{attachment_dir}' not found.")
        return

    print("--- Starting PDF Indexing ---")
    
    # First, clear any old documents from the same source
    # This prevents re-indexing the same file
    all_files = [f for f in os.listdir(attachment_dir) if f.endswith('.pdf')]
    for pdf_file in all_files:
        print(f"Deleting old entries for: {pdf_file}")
        supabase.table('documents').delete().eq('source_filename', pdf_file).execute()

    # Now, process and embed each PDF
    for pdf_file in all_files:
        print(f"\nProcessing: {pdf_file}")
        file_path = os.path.join(attachment_dir, pdf_file)
        
        pdf_text = parse_pdf(file_path)
        if not pdf_text:
            print(f"Skipping {pdf_file}: No text extracted.")
            continue
            
        chunks = split_text(pdf_text)
        print(f"Split into {len(chunks)} chunks.")
        
        documents_to_insert = []
        for i, chunk in enumerate(chunks):
            embedding = get_embedding(chunk)
            if embedding:
                documents_to_insert.append({
                    "source_filename": pdf_file,
                    "content": chunk,
                    "embedding": embedding
                })
            print(f"  ...created embedding for chunk {i+1}/{len(chunks)}")
        
        # Batch insert all chunks for this PDF
        if documents_to_insert:
            supabase.table('documents').insert(documents_to_insert).execute()
            print(f"Successfully inserted {len(documents_to_insert)} chunks for {pdf_file}.")

    print("\n--- Indexing Complete ---")

if __name__ == "__main__":
    main()