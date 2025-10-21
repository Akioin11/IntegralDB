import os
import csv
import json
import pdfplumber
import google.generativeai as genai # <-- CHANGED
from supabase import create_client, Client

# --- 1. CONFIGURATION ---

# Load credentials from environment variables
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") # <-- CHANGED
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# Initialize clients
try:
    # Configure the Gemini client
    genai.configure(api_key=GOOGLE_API_KEY) # <-- CHANGED
    
    # Set up the model with JSON output config
    generation_config = genai.GenerationConfig(
        response_mime_type="application/json"
    )
    gemini_model = genai.GenerativeModel(
        'gemini-1.5-flash', # Use a modern, fast model
        generation_config=generation_config
    ) # <-- CHANGED
    
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Clients initialized successfully (Gemini & Supabase).")
except Exception as e:
    print(f"Error initializing clients: {e}")
    print("Please set your GOOGLE_API_KEY, SUPABASE_URL, and SUPABASE_KEY environment variables.")
    exit()

# --- 2. PARSING ---

def parse_pdf(file_path):
    """Reads all text from a PDF file."""
    if not os.path.exists(file_path):
        return ""
        
    try:
        with pdfplumber.open(file_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += page.extract_text() or ""
            return full_text
    except Exception as e:
        print(f"Error reading PDF {file_path}: {e}")
        return ""

# --- 3. LLM EXTRACTION (MODIFIED FOR GEMINI) ---

def extract_structured_data(text_content):
    """Uses Gemini to extract structured data from raw text."""
    
    # Gemini works best with the prompt and instructions combined.
    prompt = """
    You are an expert data extraction assistant.
    From the following text, extract supplier and product information.
    The text could be from an email body or a PDF (catalog, invoice).
    
    Return a single JSON object with this exact structure:
    {
      "supplier_name": "Example Supplier Inc.",
      "contact_email": "sales@example.com",
      "products": [
        {
          "product_name": "Widget A",
          "price": 199.99,
          "sku": "WID-A-123",
          "catalog_details": "Premium quality steel widget."
        }
      ]
    }
    
    Rules:
    - "supplier_name": The name of the supplier company.
    - "products": A list of product objects.
    - "price": Must be a number (float or int), no currency symbols.
    - If info is missing, use null.
    - If no products are found, return an empty "products" list.
    
    Here is the text to analyze:
    ---
    {text_content}
    ---
    """
    
    print(f"Sending {len(text_content)} chars to Gemini for extraction...")
    
    try:
        # Pass the combined prompt to the model
        response = gemini_model.generate_content(prompt.format(text_content=text_content))
        
        # The 'generation_config' ensures response.text is valid JSON
        return json.loads(response.text)
        
    except Exception as e:
        print(f"Error calling Gemini: {e}")
        # You can print response.prompt_feedback here for debugging
        return None

# --- 4. DATABASE INSERTION ---
# (This function is UNCHANGED from the previous guide)

def insert_data_into_db(data, email_id):
    """Inserts the structured data into Supabase Postgres tables."""
    
    supplier_name = data.get("supplier_name")
    if not supplier_name:
        print("Skipping insert: No supplier name found.")
        return

    try:
        # Upsert Supplier
        supplier_row = supabase.table("suppliers").upsert(
            {
                "supplier_name": supplier_name,
                "contact_email": data.get("contact_email"),
                "extracted_from_email_id": email_id
            },
            on_conflict="supplier_name" # Use the UNIQUE column
        ).execute().data[0]
        
        supplier_db_id = supplier_row['id']
        print(f"Upserted supplier: {supplier_name} (ID: {supplier_db_id})")

        # Batch Insert Products
        products_to_insert = []
        for product in data.get("products", []):
            if product.get("product_name") and product.get("price") is not None:
                products_to_insert.append({
                    "supplier_id": supplier_db_id,
                    "product_name": product.get("product_name"),
                    "price": product.get("price"),
                    "sku": product.get("sku"),
                    "catalog_details": product.get("catalog_details")
                })
            
        if products_to_insert:
            product_rows = supabase.table("products").insert(products_to_insert).execute()
            print(f"Inserted {len(product_rows.data)} products for {supplier_name}.")
            
    except Exception as e:
        print(f"Error inserting into Supabase: {e}")

# --- 5. MAIN ORCHESTRATION ---
# (This function is UNCHANGED from the previous guide)

def main():
    """Main function to run the Day 2 pipeline."""
    csv_file = "supplier_emails.csv" # From Day 1
    
    if not os.path.exists(csv_file):
        print(f"Error: {csv_file} not found. Did you run Day 1?")
        return

    print("--- Starting Day 2: Processing and Extraction (Gemini) ---")
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            email_id = row['id']
            print(f"\nProcessing Email ID: {email_id}")
            
            # 1. Combine all text sources
            full_text_content = ""
            full_text_content += f"Email Subject: {row['subject']}\n"
            full_text_content += f"Email Body:\n{row['body']}\n\n"
            
            # 2. Parse PDF attachments
            if row['attachments']:
                pdf_path = row['attachments'].split(", ")[0]
                pdf_text = parse_pdf(pdf_path)
                if pdf_text:
                    full_text_content += f"--- PDF Attachment Content ({pdf_path}) ---\n"
                    full_text_content += pdf_text
            
            # 3. Extract with LLM (now using Gemini)
            extracted_data = extract_structured_data(full_text_content)
            
            if extracted_data:
                # 4. Insert into Database
                insert_data_into_db(extracted_data, email_id)
            else:
                print(f"No data extracted for Email ID: {email_id}")

    print("\n--- Day 2 Complete ---")
    print("Structured data has been extracted and saved to Supabase.")

if __name__ == "__main__":
    main()