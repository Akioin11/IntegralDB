import os
import csv
import json
import pdfplumber
import google.generativeai as genai
from supabase import create_client, Client
import logging
from pydantic import BaseModel, Field # <-- Field is no longer used, but we'll leave the import
from typing import List, Optional
from dotenv import load_dotenv, find_dotenv

# --- 0. LOAD ENVIRONMENT VARIABLES ---
# Robust .env loading: find from current working dir or fall back to script dir
dotenv_path = find_dotenv(usecwd=True)
if dotenv_path:
    load_dotenv(dotenv_path)
else:
    from pathlib import Path
    alt_env = Path(__file__).resolve().parent / ".env"
    if alt_env.exists():
        load_dotenv(alt_env)

# Suppress pdfplumber warnings
logging.getLogger("pdfplumber").setLevel(logging.ERROR)

# --- 0. PYDANTIC MODELS (FIXED) ---
#
# *** THIS IS THE FIX ***
# We are removing all `Field(...)` calls.
# The `google-generativeai` library has a bug and cannot
# parse the `Field` object.
# Using simple type hints like `Optional[str]` works.
#

class Product(BaseModel):
    """Represents a single product"""
    product_name: str
    price: Optional[float]
    sku: Optional[str]
    catalog_details: Optional[str]
    product_specifications: Optional[str]

class SupplierData(BaseModel):
    """The root object for all extracted data from a document"""
    supplier_name: str
    contact_email: Optional[str]
    contact_phone: Optional[str]
    products: List[Product]

# --- 1. CONFIGURATION ---

def _get_env(name: str):
    v = os.environ.get(name)
    if v is None:
        return None
    return v.strip().strip('"').strip("'")

GOOGLE_API_KEY = _get_env("GOOGLE_API_KEY")
SUPABASE_URL = _get_env("SUPABASE_URL")
SUPABASE_KEY = _get_env("SUPABASE_KEY")

if not all([GOOGLE_API_KEY, SUPABASE_URL, SUPABASE_KEY]):
    print("Error: Missing environment variables.")
    print("Please ensure you have a .env file with GOOGLE_API_KEY, SUPABASE_URL, and SUPABASE_KEY.")
    print(f"CWD: {os.getcwd()}")
    print(f"find_dotenv found: {dotenv_path}")
    exit(1)

try:
    genai.configure(api_key=GOOGLE_API_KEY)
    
    generation_config = genai.GenerationConfig(
        response_mime_type="application/json",
        response_schema=SupplierData  # <-- This will now parse correctly
    )
    
    gemini_model = genai.GenerativeModel(
        'gemini-2.5-flash',
        generation_config=generation_config
    )
    
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Clients initialized (Gemini w/ Pydantic & Supabase).")
except Exception as e:
    print(f"Error initializing clients: {e}") # <-- This is where it was failing
    exit()

# --- 2. PARSING ---
# (Unchanged)
def parse_pdf(file_path):
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

# --- 3. LLM EXTRACTION (FIXED) ---

def extract_structured_data(text_content: str) -> Optional[SupplierData]:
    """
    Uses Gemini to extract structured data using the Pydantic schema.
    Returns an instantiated SupplierData object or None.
    """
    
    prompt = f"""
    You are an expert data extraction assistant.
    Analyze the following text from a supplier email or PDF.
    Extract the supplier's name, contact email, contact phone,
    and a complete list of all products mentioned.
    
    For each product, extract:
    - product_name
    - price (as a number)
    - sku
    - catalog_details (general description)
    - product_specifications (technical details like size, material, etc.)
    
    --- TEXT TO ANALYZE ---
    {text_content}
    ---
    """
    
    print(f"Sending {len(text_content)} chars to Gemini for structured extraction...")
    
    try:
        response = gemini_model.generate_content(prompt)
        
        # *** THIS IS THE FIX ***
        # The 'genai.GenerativeModel' client puts the raw JSON string in .text
        # We just need to parse it ourselves.
        
        print(f"[Gemini Raw JSON Response]: {response.text}")
        
        # 1. Parse the string into a Python dict
        data_dict = json.loads(response.text)
        
        # 2. Parse the dict into our Pydantic model
        supplier_data = SupplierData(**data_dict)
        
        return supplier_data
        
    except json.JSONDecodeError as json_err:
        print(f"!!! Failed to decode JSON from Gemini. Error: {json_err}")
        print(f"!!! Raw response was: {response.text}")
        return None
    except Exception as e:
        # Catch Pydantic validation errors or other issues
        print(f"Error parsing Gemini response into Pydantic model: {e}")
        return None
    
# --- 4. DATABASE INSERTION ---
# (Unchanged)
def insert_data_into_db(data: SupplierData, email_id: str):
    
    if not data.supplier_name:
        print("Skipping insert: No supplier name found in extracted data.")
        return

    try:
        supplier_row = supabase.table("suppliers").upsert(
            {
                "supplier_name": data.supplier_name,
                "contact_email": data.contact_email,
                "contact_phone": data.contact_phone,
                "extracted_from_email_id": email_id
            },
            on_conflict="supplier_name"
        ).execute().data[0]
        
        supplier_db_id = supplier_row['id']
        print(f"Upserted supplier: {data.supplier_name} (ID: {supplier_db_id})")

        products_to_insert = []
        for product in data.products:
            if product.product_name:
                products_to_insert.append({
                    "supplier_id": supplier_db_id,
                    "product_name": product.product_name,
                    "price": product.price,
                    "sku": product.sku,
                    "catalog_details": product.catalog_details,
                    "product_specifications": product.product_specifications
                })
            
        if products_to_insert:
            product_rows = supabase.table("products").insert(products_to_insert).execute()
            print(f"Inserted {len(product_rows.data)} products for {data.supplier_name}.")
        else:
            print("No valid products found in extracted data to insert.")
            
    except Exception as e:
        print(f"!!! Error inserting into Supabase: {e}")
        print("!!! Check your Supabase schema and RLS policies.")

# --- 5. MAIN ORCHESTRATION ---
# (Unchanged)
def main():
    csv_file = "supplier_emails.csv"
    if not os.path.exists(csv_file):
        print(f"Error: {csv_file} not found. Did you run Day 1?")
        return

    print("--- Starting Day 2: Processing and Extraction (Gemini + Pydantic) ---")
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            email_id = row['id']
            print(f"\nProcessing Email ID: {email_id}")
            
            full_text_content = ""
            full_text_content += f"Email Subject: {row['subject']}\n"
            full_text_content += f"Email Body:\n{row['body']}\n\n"
            
            if row['attachments']:
                attachment_paths = row['attachments'].split(", ")
                for pdf_path in attachment_paths:
                    if pdf_path.endswith('.pdf'):
                        pdf_text = parse_pdf(pdf_path)
                        if pdf_text:
                            full_text_content += f"\n--- PDF Attachment Content ({pdf_path}) ---\n"
                            full_text_content += pdf_text
            
            if not full_text_content.strip():
                 print("Skipping: No text content found in email or PDF.")
                 continue

            extracted_data = extract_structured_data(full_text_content)
            
            if extracted_data:
                insert_data_into_db(extracted_data, email_id)
            else:
                print(f"No data extracted or saved for Email ID: {email_id}")

    print("\n--- Day 2 Complete ---")

if __name__ == "__main__":
    main()