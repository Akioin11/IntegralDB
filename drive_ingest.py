import os
import io
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

# Add both scopes.
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]

# This is the same auth function from Day 1, just renamed.
def get_drive_service():
    """Authenticates with Google API and returns a Drive service object."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            
    try:
        service = build('drive', 'v3', credentials=creds)
        print("Google Drive service created successfully.")
        return service
    except HttpError as error:
        print(f'An error occurred: {error}')
        return None

def download_file(service, file_id, file_name, mime_type):
    """Downloads a file from Drive and saves it as a PDF."""
    
    # Ensure attachments folder exists
    if not os.path.exists('attachments'):
        os.makedirs('attachments')
        
    # Standardize the output name to .pdf
    output_filename = os.path.splitext(file_name)[0] + ".pdf"
    output_filepath = os.path.join('attachments', output_filename)
    
    try:
        if "google-apps.document" in mime_type:
            # Google Docs must be exported
            print(f"Exporting Google Doc: {file_name}...")
            request = service.files().export_media(
                fileId=file_id, 
                mimeType='application/pdf'
            )
        else:
            # Regular files (like PDFs) can be downloaded directly
            print(f"Downloading file: {file_name}...")
            request = service.files().get_media(fileId=file_id)
        
        # Execute the download
        fh = io.FileIO(output_filepath, 'wb')
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            print(f"  Download {int(status.progress() * 100)}%.")
        
        print(f"Saved to {output_filepath}")
        
    except HttpError as error:
        print(f"An error occurred downloading {file_name}: {error}")

def fetch_drive_files(service):
    """Finds all PDFs and Google Docs in the user's Drive."""
    
    # Query for all PDFs OR Google Docs
    query = "(mimeType='application/pdf' or mimeType='application/vnd.google-apps.document')"
    
    try:
        results = service.files().list(
            q=query,
            pageSize=100, # Get up to 100 files
            fields="nextPageToken, files(id, name, mimeType)"
        ).execute()
        
        items = results.get('files', [])
        
        if not items:
            print('No PDFs or Google Docs found in Drive.')
            return

        print(f"Found {len(items)} files to process...")
        for item in items:
            download_file(service, item['id'], item['name'], item['mimeType'])
            
    except HttpError as error:
        print(f'An error occurred fetching files: {error}')

if __name__ == '__main__':
    service = get_drive_service()
    if service:
        fetch_drive_files(service)
    
    print("\n--- Google Drive Ingestion Complete ---")
    print("Run 'python day3_embed.py' to add these new files to your RAG system.")