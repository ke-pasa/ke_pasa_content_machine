"""Check article age for testing the 5-day filter"""
import sys
sys.path.insert(0, 'c:\\Development\\ke_pasa_content_machine')

from workers.tools.firebase_client import FirebaseClient
from datetime import datetime, timezone

client = FirebaseClient()
db = client.db

# Get first CATEGORIZED article
docs = db.collection('articles').where('status', '==', 'CATEGORIZED').limit(5).stream()

for doc in docs:
    data = doc.to_dict()
    print(f"\n=== Document {doc.id} ===")
    print(f"Status: {data.get('status')}")
    print(f"Score: {data.get('total_score')}")
    
    # Check all possible date fields
    published_at = data.get('published_at') or data.get('published') or data.get('pub_date')
    created_at = data.get('created_at')
    
    print(f"published_at: {data.get('published_at')}")
    print(f"published: {data.get('published')}")
    print(f"pub_date: {data.get('pub_date')}")
    print(f"created_at: {created_at}")
    
    if published_at:
        try:
            if isinstance(published_at, str):
                pub_dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
            else:
                pub_dt = published_at
            
            age_days = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 86400
            print(f"Article age: {age_days:.1f} days")
            print(f"Should skip (>5 days): {age_days > 5}")
        except Exception as e:
            print(f"Error parsing date: {e}")
