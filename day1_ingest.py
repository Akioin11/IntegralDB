import os
import base64
import csv
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import logging

# --- Configuration ---
# This scope allows us to read emails.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
TOKEN_PATH = 'token.json'
CREDENTIALS_PATH = 'credentials.json'
ATTACHMENT_DIR = Path('attachments')
OUTPUT_CSV = 'emails.csv'
MAX_EMAILS = 10  # How many emails to fetch

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def setup_api_service():
    """
    Authenticates with the Gmail API and returns a service object.
    Handles the OAuth2 flow automatically.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens.
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    
    # If there are no (valid) credentials, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # This runs the local auth flow, opening a browser window
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())
            
    try:
        service = build('gmail', 'v1', credentials=creds)
        logging.info("Gmail API service created successfully.")
        return service
    except HttpError as error:
        logging.error(f'An error occurred building the service: {error}')
        return None

def get_email_body(payload):
    """
    Parses the email payload to find the 'text/plain' body.
    """
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain' and 'data' in part['body']:
                # Found plain text body
                return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
            elif part['mimeType'] == 'multipart/alternative':
                # Recurse into multipart
                return get_email_body(part)
    elif 'body' in payload and payload['mimeType'] == 'text/plain':
        # Top-level body is plain text
        return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
    
    return "" # No plain text body found

def download_attachment(service, msg_id, part, save_dir):
    """
    Downloads a single PDF attachment.
    """
    filename = part.get('filename')
    if not filename.lower().endswith('.pdf'):
        return None # Skip non-PDF files

    attachment_id = part['body'].get('attachmentId')
    if not attachment_id:
        return None

    try:
        # Get the attachment data
        attachment = service.users().messages().attachments().get(
            userId='me', messageId=msg_id, id=attachment_id
        ).execute()
        
        data = attachment.get('data')
        if not data:
            return None
            
        file_data = base64.urlsafe_b64decode(data)
        
        # Create a unique-ish filepath
        filepath = save_dir / f"{msg_id}_{filename}"
        
        with open(filepath, 'wb') as f:
            f.write(file_data)
        
        logging.info(f"Downloaded attachment: {filepath}")
        return str(filepath) # Return the path as a string
        
    except HttpError as error:
        logging.error(f'An error occurred downloading attachment: {error}')
        return None

def fetch_and_process_emails(service, max_results):
    """
    Fetches the latest emails, processes them, and downloads PDFs.
    Returns a list of dictionaries, one for each email.
    """
    email_data_list = []
    
    try:
        # Get the list of message IDs
        results = service.users().messages().list(
            userId='me', labelIds=['INBOX'], maxResults=max_results
        ).execute()
        messages = results.get('messages', [])

        if not messages:
            logging.warning("No emails found.")
            return []

        logging.info(f"Found {len(messages)} emails. Processing...")

        for msg_summary in messages:
            msg_id = msg_summary['id']
            
            # Get the full email message
            msg = service.users().messages().get(
                userId='me', id=msg_id, format='full'
            ).execute()
            
            payload = msg.get('payload', {})
            headers = payload.get('headers', [])
            
            # Extract sender, subject
            email_info = {
                'id': msg_id,
                'sender': '',
                'subject': '',
                'body': '',
                'attachment_paths': []
            }

            for header in headers:
                name = header.get('name')
                if name == 'From':
                    email_info['sender'] = header.get('value')
                elif name == 'Subject':
                    email_info['subject'] = header.get('value')
            
            # Get the body
            email_info['body'] = get_email_body(payload)

            # Process parts (attachments)
            if 'parts' in payload:
                for part in payload['parts']:
                    if part.get('filename'):
                        filepath = download_attachment(service, msg_id, part, ATTACHMENT_DIR)
                        if filepath:
                            email_info['attachment_paths'].append(filepath)
            
            email_data_list.append(email_info)
            logging.info(f"Processed email from: {email_info['sender']}")

    except HttpError as error:
        logging.error(f'An error occurred fetching emails: {error}')

    return email_data_list

def save_to_csv(data_list, filename):
    """
    Saves the extracted email data to a CSV file.
    """
    if not data_list:
        logging.warning("No data to save to CSV.")
        return

    # Create directory if it doesn't exist
    Path(filename).parent.mkdir(parents=True, exist_ok=True)

    headers = ['id', 'sender', 'subject', 'body', 'attachment_paths']
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in data_list:
            # Join list of attachment paths into a single string
            row['attachment_paths'] = ";".join(row['attachment_paths'])
            writer.writerow(row)
            
    logging.info(f"Successfully saved data to {filename}")

def main():
    """
    Main execution flow for Day 1.
    """
    logging.info("--- Starting Day 1: Data Ingestion ---")
    
    # Ensure attachment directory exists
    ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Authenticate and build service
    service = setup_api_service()
    if not service:
        logging.error("Failed to create Gmail service. Exiting.")
        return
        
    # 2. Fetch emails and download attachments
    email_data = fetch_and_process_emails(service, max_results=MAX_EMAILS)
    
    # 3. Save results to CSV
    save_to_csv(email_data, OUTPUT_CSV)
    
    logging.info("--- Day 1 Complete ---")

if __name__ == '__main__':
    main()