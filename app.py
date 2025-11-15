import os
from flask import Flask, render_template, request
from supabase import create_client, Client

# --- CONFIGURATION ---
# We will get these from Render's Environment Variables
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
# --- END CONFIGURATION ---

# Initialize Flask app
app = Flask(__name__)

# Initialize Supabase client
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"Error initializing Supabase client: {e}")
    supabase = None

@app.route('/')
def index():
    if not supabase:
        return "Error: Supabase client not initialized. Check environment variables."
        
    try:
        # Fetch all data from the 'applications' table
        response = supabase.table('application').select("*").execute()
        
        if response.data:
            # Pass the list of data to the HTML
            return render_template('index.html', das=response.data)
        else:
            return f"No data found or error: {response}"
            
    except Exception as e:
        return f"An error occurred while fetching data: {e}"

if __name__ == '__main__':
    # Gunicorn will run this file, so this part is for local testing
    app.run(debug=True)