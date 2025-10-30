"""Unified ingestion script.

Downloads attachments from Gmail and files from Google Drive, then parses
PDFs, creates embeddings via Google's generative AI, and uploads documents
and embeddings to Supabase in batches.

Usage:
  python unified_ingest.py

Requires:
  - credentials.json (Google OAuth client)
  - token.json will be created after first auth
  - .env with GOOGLE_API_KEY, SUPABASE_URL, SUPABASE_KEY
"""
import os
import io
import time
import base64
from pathlib import Path
from typing import List, Tuple, Set
import json

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


# Combined scopes for Gmail + Drive read-only
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]

STATE_FILE = Path('ingest_state.json')


def load_state():
    if not STATE_FILE.exists():
        return {'drive': {}, 'emails': {}, 'uploaded': []}
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {'drive': {}, 'emails': {}, 'uploaded': []}


def save_state(state: dict):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Failed to save ingest state: {e}")


def load_config():
    load_dotenv()
    cfg = {
        'GOOGLE_API_KEY': os.environ.get('GOOGLE_API_KEY'),
        'SUPABASE_URL': os.environ.get('SUPABASE_URL'),
        'SUPABASE_KEY': os.environ.get('SUPABASE_KEY'),
    }
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")
    return cfg


def get_credentials():
    creds = None
    token_path = Path('token.json')
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w', encoding='utf-8') as fh:
            fh.write(creds.to_json())

    return creds


def get_gmail_service(creds):
    try:
        return build('gmail', 'v1', credentials=creds)
    except HttpError as e:
        print(f"Failed to create Gmail service: {e}")
        return None


def get_drive_service(creds):
    try:
        return build('drive', 'v3', credentials=creds)
    except HttpError as e:
        print(f"Failed to create Drive service: {e}")
        return None


def ensure_attachments_dir():
    p = Path('attachments')
    p.mkdir(exist_ok=True)
    return p


# ---------------- Gmail helpers ----------------
def get_email_body(parts):
    if not parts:
        return ""
    for part in parts:
        if part.get('mimeType') == 'text/plain' and part.get('body', {}).get('data'):
            data = part['body']['data']
            return base64.urlsafe_b64decode(data).decode('utf-8')
        elif part.get('mimeType') == 'multipart/alternative':
            return get_email_body(part.get('parts', []))
    return ""


def get_attachments(service, user_id, msg_id, parts) -> List[str]:
    paths = []
    if not parts:
        return paths
    attachments_dir = ensure_attachments_dir()
    for part in parts:
        filename = part.get('filename')
        if filename and filename.lower().endswith('.pdf') and part.get('body', {}).get('attachmentId'):
            att_id = part['body']['attachmentId']
            try:
                attachment = service.users().messages().attachments().get(
                    userId=user_id, messageId=msg_id, id=att_id
                ).execute()
                data = base64.urlsafe_b64decode(attachment['data'].encode('UTF-8'))
                path = attachments_dir / filename
                with open(path, 'wb') as fh:
                    fh.write(data)
                print(f"Saved email attachment: {path}")
                paths.append(str(path))
            except HttpError as e:
                print(f"Failed to fetch attachment {filename}: {e}")
    return paths



def fetch_latest_emails(service, max_results=10, state=None) -> Tuple[List[str], Set[str]]:
    """Fetches recent emails and downloads PDF attachments. Returns list of file paths and a reprocess set."""
    try:
        results = service.users().messages().list(userId='me', labelIds=['INBOX'], maxResults=max_results).execute()
        messages = results.get('messages', [])
        if not messages:
            print('No new emails found.')
            return [], set()
        print(f"Found {len(messages)} emails. Checking for attachments...")
        saved = []
        reprocess = set()
        for msg in messages:
            msg_id = msg['id']
            full = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
            payload = full.get('payload', {})
            parts = payload.get('parts', [])
            # iterate parts manually so we can skip already-downloaded attachments
            attachments_dir = ensure_attachments_dir()
            for part in parts:
                filename = part.get('filename')
                att_id = part.get('body', {}).get('attachmentId')
                if filename and filename.lower().endswith('.pdf') and att_id:
                    key = f"{msg_id}:{att_id}"
                    if state and state.get('emails', {}).get(key):
                        # already downloaded previously
                        print(f"Skipping already-downloaded email attachment {filename} (message {msg_id})")
                        continue
                    try:
                        attachment = service.users().messages().attachments().get(
                            userId='me', messageId=msg_id, id=att_id
                        ).execute()
                        data = base64.urlsafe_b64decode(attachment['data'].encode('UTF-8'))
                        path = attachments_dir / filename
                        with open(path, 'wb') as fh:
                            fh.write(data)
                        print(f"Saved email attachment: {path}")
                        saved.append(str(path))
                        if state is not None:
                            state.setdefault('emails', {})[key] = str(path)
                    except HttpError as e:
                        print(f"Failed to fetch attachment {filename}: {e}")
        return saved, reprocess
    except HttpError as e:
        print(f"Error fetching emails: {e}")
        return [], set()


# ---------------- Drive helpers ----------------
def download_drive_file(service, file_id, file_name, mime_type) -> str:
    attachments_dir = ensure_attachments_dir()
    output_filename = os.path.splitext(file_name)[0] + ".pdf"
    output_path = attachments_dir / output_filename
    try:
        if 'google-apps.document' in mime_type:
            request = service.files().export_media(fileId=file_id, mimeType='application/pdf')
        else:
            request = service.files().get_media(fileId=file_id)
        fh = io.FileIO(str(output_path), 'wb')
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        print(f"Downloaded Drive file to {output_path}")
        return str(output_path)
    except HttpError as e:
        print(f"Error downloading {file_name}: {e}")
        return ''


def fetch_drive_pdfs(service, state=None) -> Tuple[List[str], Set[str]]:
    query = "(mimeType='application/pdf' or mimeType='application/vnd.google-apps.document')"
    try:
        results = service.files().list(q=query, pageSize=200, fields="files(id,name,mimeType,modifiedTime)").execute()
        items = results.get('files', [])
        if not items:
            print('No Drive PDFs/Docs found.')
            return [], set()
        print(f"Found {len(items)} Drive files to download...")
        saved = []
        reprocess = set()
        for item in items:
            fid = item['id']
            name = item.get('name')
            mtime = item.get('modifiedTime')
            already = False
            if state and state.get('drive', {}).get(fid):
                prev = state['drive'][fid]
                if prev.get('modifiedTime') == mtime and Path(prev.get('path', '')).exists():
                    print(f"Skipping unchanged Drive file: {name}")
                    already = True
            if already:
                continue
            path = download_drive_file(service, fid, name, item.get('mimeType'))
            if path:
                saved.append(path)
                if state is not None:
                    # if file existed previously but modifiedTime changed, mark for reprocess
                    if state.get('drive', {}).get(fid) and state['drive'][fid].get('modifiedTime') != mtime:
                        reprocess.add(os.path.basename(path))
                    state.setdefault('drive', {})[fid] = {'name': name, 'modifiedTime': mtime, 'path': str(path)}
        return saved, reprocess
    except HttpError as e:
        print(f"Error listing drive files: {e}")
        return [], set()


# ---------------- Parsing / Embedding / Upload ----------------
def parse_pdf(file_path: str) -> str:
    if not os.path.exists(file_path):
        return ''
    try:
        with pdfplumber.open(file_path) as pdf:
            text = ''
            for page in pdf.pages:
                text += page.extract_text(x_tolerance=1) or ''
            return text
    except Exception as e:
        print(f"Error parsing PDF {file_path}: {e}")
        return ''


def split_text(text, chunk_size=1000, chunk_overlap=200):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += (chunk_size - chunk_overlap)
    return chunks


def get_embedding(text, model='models/text-embedding-004'):
    try:
        result = genai.embed_content(model=model, content=text, task_type='RETRIEVAL_DOCUMENT')
        return result['embedding']
    except Exception as e:
        print(f"Embedding error: {e}")
        if 'rate limit' in str(e).lower():
            time.sleep(5)
            return get_embedding(text, model)
        return None


def upload_documents_to_supabase(supabase: Client, documents: List[dict]):
    if not documents:
        return
    try:
        supabase.table('documents').insert(documents).execute()
    except Exception as e:
        print(f"Failed to insert batch: {e}")


def process_and_index_files(supabase: Client, embedding_model: str, files: List[str], reprocess_files: Set[str], state: dict):
    if not files:
        print('No files to index.')
        return
    for file in files:
        fname = os.path.basename(file)
        print(f"Processing {fname}...")
        # If this file is not in reprocess set, check whether it's already uploaded
        if fname not in reprocess_files:
            try:
                resp = supabase.table('documents').select('id').eq('source_filename', fname).limit(1).execute()
                if resp.data:
                    print(f"  Skipping {fname} because it already exists in Supabase.")
                    # mark as uploaded in state
                    if state is not None:
                        state.setdefault('uploaded', [])
                        if fname not in state['uploaded']:
                            state['uploaded'].append(fname)
                    continue
            except Exception as e:
                print(f"  Could not check Supabase for {fname}: {e}")
        else:
            # delete previous entries for updated files
            try:
                print(f"  Replacing existing entries for {fname} (file changed)")
                supabase.table('documents').delete().eq('source_filename', fname).execute()
            except Exception as e:
                print(f"  Could not delete old entries for {fname}: {e}")

        text = parse_pdf(file)
        if not text.strip():
            print(f"  No text extracted from {fname}, skipping.")
            continue
        chunks = split_text(text)
        docs = []
        for i, chunk in enumerate(chunks):
            clean = chunk.replace('\u0000', '').replace('\x00', '')
            if not clean.strip():
                continue
            emb = get_embedding(clean, model=embedding_model)
            if emb:
                docs.append({
                    'source_filename': fname,
                    'content': clean,
                    'embedding': emb
                })
        if docs:
            print(f"  Uploading {len(docs)} chunks for {fname} to Supabase...")
            upload_documents_to_supabase(supabase, docs)
            # mark uploaded
            if state is not None:
                state.setdefault('uploaded', [])
                if fname not in state['uploaded']:
                    state['uploaded'].append(fname)
                save_state(state)
        else:
            print(f"  No valid chunks for {fname} to upload.")


def main():
    cfg = load_config()
    genai.configure(api_key=cfg['GOOGLE_API_KEY'])
    supabase: Client = create_client(cfg['SUPABASE_URL'], cfg['SUPABASE_KEY'])

    # Load persistent state for differential runs
    state = load_state()

    creds = get_credentials()
    gmail = get_gmail_service(creds)
    drive = get_drive_service(creds)

    downloaded = []
    reprocess = set()
    if gmail:
        files, r = fetch_latest_emails(gmail, max_results=50, state=state)
        downloaded += files
        reprocess.update(r)
    if drive:
        files, r = fetch_drive_pdfs(drive, state=state)
        downloaded += files
        reprocess.update(r)

    # Deduplicate file list
    downloaded = list(dict.fromkeys(downloaded))

    if not downloaded:
        print('No attachments or drive files downloaded. Exiting.')
        save_state(state)
        return

    print(f"Total files to index: {len(downloaded)}")
    process_and_index_files(supabase, 'models/text-embedding-004', downloaded, reprocess, state)
    save_state(state)
    print('\n--- Unified ingestion complete ---')


if __name__ == '__main__':
    main()
