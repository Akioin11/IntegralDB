import os
import pdfplumber
from supabase import create_client, Client
from dotenv import load_dotenv
from litellm import embedding  # <-- CHANGED

# --- 0. LOAD CONFIG ---
load_dotenv()
# GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") # <-- REMOVED
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# genai.configure(api_key=GOOGLE_API_KEY) # <-- REMOVED
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
print("Clients initialized (Supabase).")

# --- 1. CHUNKING & PARSING ---
# (This section is unchanged)

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

# --- 2. EMBEDDING (MODIFIED FOR OLLAMA) ---

def get_embedding(text, model="nomic-embed-text"):
    """Generates an embedding for a text chunk using local Ollama."""
    
    # Nomic *requires* a task-specific prefix.
    # For storing documents in a DB, we use 'search_document'.
    prefixed_text = f"search_document: {text}"
    
    try:
        # We must tell litellm to prefix the model with "ollama/"
        response = embedding(
            model=f"ollama/{model}", 
            input=prefixed_text
        )
        # Extract the vector from the response
        return response.data[0].embedding
    except Exception as e:
        print(f"Error creating local embedding: {e}")
        # This might fail if Ollama isn't running
        print("!!! Make sure Ollama is running in your terminal. !!!")
        return None

# --- 3. MAIN INDEXING LOGIC ---
# (This section is unchanged, but will now use the new get_embedding function)

def main():
    attachment_dir = "attachments"
    if not os.path.exists(attachment_dir):
        print(f"Error: Directory '{attachment_dir}' not found.")
        return

    print("--- Starting PDF Indexing (using local Ollama) ---")
    
    # Get all PDF files
    all_files = [f for f in os.listdir(attachment_dir) if f.endswith('.pdf')]
    
    # First, clear any old documents from the same sources
    for pdf_file in all_files:
        print(f"Deleting old entries for: {pdf_file}")
        try:
            supabase.table('documents').delete().eq('source_filename', pdf_file).execute()
        except Exception as e:
            print(f"Could not delete old entries for {pdf_file}: {e}")

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
            
            # Sanitize the chunk to remove null bytes
            clean_chunk = chunk.replace('\u0000', '').replace('\x00', '')
            
            if not clean_chunk.strip():
                print(f"  ...skipping empty/null chunk {i+1}/{len(chunks)}")
                continue
                
            embedding = get_embedding(clean_chunk) # Embed the *clean* text
            if embedding:
                documents_to_insert.append({
                    "source_filename": pdf_file,
                    "content": clean_chunk, # Insert the *clean* text
                    "embedding": embedding
                })
                print(f"  ...created embedding for chunk {i+1}/{len(chunks)}")
            else:
                print(f"  ...FAILED to create embedding for chunk {i+1}")
        
        # Batch insert all chunks for this PDF
        if documents_to_insert:
            try:
                supabase.table('documents').insert(documents_to_insert).execute()
                print(f"Successfully inserted {len(documents_to_insert)} chunks for {pdf_file}.")
            except Exception as e:
                print(f"!!! FAILED TO INSERT BATCH for {pdf_file}: {e}")
                print("!!! This PDF might have other encoding issues, but the script will continue.")

    print("\n--- Indexing Complete ---")

if __name__ == "__main__":
    main()