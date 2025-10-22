import os.path
import base64
import csv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# We use 'readonly' as we are only reading emails.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/drive.readonly']

def get_gmail_service():
    """Authenticates with Gmail API and returns a service object."""
    creds = None
    # The file token.json stores the user's access and refresh tokens.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # This line requires the 'credentials.json' file you downloaded.
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            
    try:
        service = build('gmail', 'v1', credentials=creds)
        print("Gmail service created successfully.")
        return service
    except HttpError as error:
        print(f'An error occurred: {error}')
        return None
    
def get_email_body(parts):
    """Parses the 'parts' of an email to find the text/plain body."""
    if not parts:
        return ""
        
    for part in parts:
        if part['mimeType'] == 'text/plain':
            # Decode the base64 encoded email body
            data = part['body']['data']
            return base64.urlsafe_b64decode(data).decode('utf-8')
        elif part['mimeType'] == 'multipart/alternative':
            # Recurse into nested parts
            return get_email_body(part.get('parts', []))
    return "" # Fallback

def get_attachments(service, user_id, msg_id, parts):
    """Finds PDF attachments, downloads them, and returns their paths."""
    attachment_paths = []
    if not parts:
        return attachment_paths

    for part in parts:
        if part.get('filename') and part['filename'].endswith('.pdf'):
            if part['body'].get('attachmentId'):
                attachment_id = part['body']['attachmentId']
                attachment = service.users().messages().attachments().get(
                    userId=user_id, messageId=msg_id, id=attachment_id
                ).execute()
                
                # Decode base64 data
                file_data = base64.urlsafe_b64decode(attachment['data'].encode('UTF-8'))
                
                # Create 'attachments' directory if it doesn't exist
                if not os.path.exists('attachments'):
                    os.makedirs('attachments')
                
                # Save the file
                path = os.path.join('attachments', part['filename'])
                with open(path, 'wb') as f:
                    f.write(file_data)
                attachment_paths.append(path)
                print(f"Downloaded attachment: {path}")
                
    return attachment_paths

def fetch_latest_emails(service, max_results=10):
    """Fetches the latest emails and extracts required info."""
    try:
        # Get the list of latest messages
        results = service.users().messages().list(
            userId='me', 
            labelIds=['INBOX'], 
            maxResults=max_results
        ).execute()
        messages = results.get('messages', [])
        
        email_data_list = []
        if not messages:
            print("No new emails found.")
            return []

        print(f"Found {len(messages)} emails. Processing...")
        
        for msg_summary in messages:
            msg_id = msg_summary['id']
            # Get the full email message
            msg = service.users().messages().get(
                userId='me', id=msg_id, format='full'
            ).execute()
            
            payload = msg.get('payload', {})
            headers = payload.get('headers', [])
            
            # Extract Sender, Subject
            sender = next((h['value'] for h in headers if h['name'] == 'From'), 'N/A')
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'N/A')
            
            # Get parts (body and attachments)
            parts = payload.get('parts', [])
            
            # Get Body
            if not parts: # Simple email with no attachments
                body_data = payload.get('body', {}).get('data', '')
                body = base64.urlsafe_b64decode(body_data).decode('utf-8') if body_data else ""
            else: # Multipart email
                body = get_email_body(parts)
            
            # Get Attachments
            attachment_paths = get_attachments(service, 'me', msg_id, parts)
            
            email_data_list.append({
                "id": msg_id,
                "sender": sender,
                "subject": subject,
                "body": body.strip(), # Clean up whitespace
                "attachments": ", ".join(attachment_paths) # Join paths if multiple
            })
            
        return email_data_list

    except HttpError as error:
        print(f'An error occurred: {error}')
        return []
    
def save_to_csv(data_list, filename="emails.csv"):
    """Saves the extracted email data to a CSV file."""
    if not data_list:
        print("No data to save.")
        return

    # Get fieldnames from the first dictionary
    fieldnames = data_list[0].keys()
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in data_list:
            writer.writerow(row)
            
    print(f"Successfully saved data to {filename}")

# --- Main execution ---
if __name__ == '__main__':
    service = get_gmail_service()
    if service:
        email_data = fetch_latest_emails(service, max_results=10)
        save_to_csv(email_data, filename="supplier_emails.csv")