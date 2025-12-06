import os
import io
import time
import json
from pathlib import Path
from typing import List, Set

import pdfplumber
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

# Configuration
load_dotenv()
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
STATE_FILE = Path('ingest_state.json')
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Sanity Check
if not all([SUPABASE_URL, SUPABASE_KEY, GOOGLE_API_KEY]):
    raise ValueError("Missing environment variables. Check your .env file.")

genai.configure(api_key=GOOGLE_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_credentials():
    """Handles Google Auth Flow."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

def get_folder_id(service, folder_name):
    """Finds folder ID by name. Assumes names are unique."""
    q = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
    results = service.files().list(q=q, fields="files(id, name)").execute()
    files = results.get('files', [])
    if not files:
        print(f"❌ Critical: Folder '{folder_name}' not found in Drive.")
        return None
    return files[0]['id']

def download_file(service, file_id, file_name, mime_type):
    """Downloads a file from Drive to local storage."""
    Path("temp_downloads").mkdir(exist_ok=True)
    clean_name = "".join([c for c in file_name if c.isalnum() or c in "._-"]).strip()
    file_path = f"temp_downloads/{clean_name}"
    
    if not file_path.endswith('.pdf'):
        file_path += '.pdf'

    print(f"⬇️  Downloading {file_name}...")
    try:
        if 'google-apps.document' in mime_type:
            request = service.files().export_media(fileId=file_id, mimeType='application/pdf')
        else:
            request = service.files().get_media(fileId=file_id)
            
        with io.FileIO(file_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
        return file_path
    except Exception as e:
        print(f"❌ Failed to download {file_name}: {e}")
        return None

def extract_text_from_pdf(path):
    """Rips text from PDF."""
    try:
        text = ""
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        return text
    except Exception as e:
        print(f"⚠️  Could not parse PDF {path}: {e}")
        return ""

def get_embedding(text):
    """Generates vector embedding using Gemini."""
    try:
        # Gemini 004 is currently the best balance of cost/performance
        result = genai.embed_content(
            model="models/Gemini-embedding-001",
            content=text,
            task_type="RETRIEVAL_DOCUMENT"
        )
        return result['embedding']
    except Exception as e:
        print(f"⚠️  Embedding failed: {e}")
        time.sleep(2) # Basic rate limit handling
        return None

def ingest_folder(service, folder_name, category_tag):
    """The heavy lifter. Downloads, parses, embeds, uploads."""
    folder_id = get_folder_id(service, folder_name)
    if not folder_id: return

    # list files in folder
    q = f"'{folder_id}' in parents and (mimeType='application/pdf' or mimeType='application/vnd.google-apps.document') and trashed=false"
    results = service.files().list(q=q, fields="files(id, name, mimeType)").execute()
    items = results.get('files', [])

    print(f"\n📂 Scanning folder '{folder_name}' (Category: {category_tag}) - Found {len(items)} files.")

    for item in items:
        # Check Supabase first to avoid re-work
        existing = supabase.table('company_knowledge').select('id').eq('source_filename', item['name']).execute()
        if existing.data:
            print(f"⏩ Skipping {item['name']} - already in database.")
            continue

        # 1. Download
        local_path = download_file(service, item['id'], item['name'], item['mimeType'])
        if not local_path: continue

        # 2. Extract Text
        raw_text = extract_text_from_pdf(local_path)
        if len(raw_text) < 50:
            print(f"⚠️  Skipping {item['name']} - Text too short or empty.")
            os.remove(local_path)
            continue

        # 3. Chunking (Simple approach: 1000 chars overlap 200)
        chunk_size = 1000
        overlap = 200
        chunks = []
        for i in range(0, len(raw_text), chunk_size - overlap):
            chunk = raw_text[i:i + chunk_size]
            chunks.append(chunk)

        # 4. Embed and Prepare Upload
        records = []
        print(f"🧠 Generating embeddings for {item['name']} ({len(chunks)} chunks)...")
        for chunk in chunks:
            vector = get_embedding(chunk)
            if vector:
                records.append({
                    "content": chunk,
                    "source_filename": item['name'],
                    "category": category_tag,  # <--- The magic sauce
                    "embedding": vector
                })
        
        # 5. Upload to Supabase
        if records:
            try:
                supabase.table('company_knowledge').insert(records).execute()
                print(f"✅ Successfully ingested {item['name']} into '{category_tag}'")
            except Exception as e:
                print(f"❌ Database Insert Error: {e}")
        
        # Cleanup
        os.remove(local_path)

def main():
    creds = get_credentials()
    service = build('drive', 'v3', credentials=creds)

    print("--- Starting Ingestion Engine ---")
    
    # Process Folder A -> Pricing
    ingest_folder(service, "Commercial", "pricing")
    
    # Process Folder B -> Specs
    ingest_folder(service, "Technical", "specs")

    print("\n--- Ingestion Complete ---")

if __name__ == "__main__":
    main()