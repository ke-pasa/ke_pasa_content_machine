"""
Article Generator Worker - generates articles from news
"""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional
from dotenv import load_dotenv

# Add root directory to path
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

load_dotenv()

from firebase_client import get_firebase_client
from content_generator import generate_article_from_news
from .config import GeneratorConfig


class ArticleGeneratorWorker:
    """Worker for generating articles from unprocessed news"""
    
    def __init__(self, config: GeneratorConfig = None):
        """
        Initialize article generator worker
        
        Args:
            config: Worker configuration
        """
        self.config = config or GeneratorConfig.from_env()
        self.config.ensure_directories()
        
        self.db = get_firebase_client().db
        self.firebase_client = get_firebase_client()
        self.instance_id = str(uuid.uuid4())[:8]
        
        print(f"[article-generator] Starting worker id={self.instance_id}")
        print(f"[article-generator] Batch size: {self.config.batch_size}")
        print(f"[article-generator] Save to files: {self.config.save_to_files}")

    def _acquire_lock(self) -> bool:
        """
        Acquires lock for article generation
        
        Returns:
            True if lock acquired, False otherwise
        """
        try:
            now = datetime.now(timezone.utc)
            locks = self.db.collection('locks').document('article_generator')
            lock_doc = locks.get()
            
            if lock_doc.exists:
                lock_data = lock_doc.to_dict()
                exp = lock_data.get('expires_at')
                
                if exp:
                    exp_dt = datetime.fromisoformat(exp)
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                    
                    if exp_dt > now:
                        holder = lock_data.get('holder_id', 'unknown')
                        print(f"[article-generator] Another instance is active (holder: {holder})")
                        return False
            
            locks.set({
                'holder_id': self.instance_id,
                'acquired_at': now.isoformat(),
                'expires_at': (now + timedelta(seconds=self.config.lock_lease_sec)).isoformat(),
                'worker_type': 'article_generator'
            })
            print(f"[article-generator] ✅ Lock acquired")
            return True
            
        except Exception as e:
            print(f"[article-generator] ❌ Lock acquisition error: {e}")
            return False

    def _release_lock(self):
        """Releases the lock"""
        try:
            self.db.collection('locks').document('article_generator').delete()
            print(f"[article-generator] ✅ Lock released")
        except Exception as e:
            print(f"[article-generator] ⚠️  Lock release error: {e}")

    def save_article_to_file(self, article_id: str, original_article: dict, 
                            generated_article: Optional[dict] = None) -> Optional[str]:
        """
        Saves article to file
        
        Args:
            article_id: Article ID
            original_article: Original article
            generated_article: Generated article
            
        Returns:
            File path or None on error
        """
        if not self.config.save_to_files:
            return None
            
        try:
            filename = f"{article_id}.txt"
            filepath = os.path.join(self.config.articles_dir, filename)
            
            content = []
            content.append("=" * 80)
            content.append(f"ARTICLE ID: {article_id}")
            content.append(f"CREATED: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            content.append("=" * 80)
            content.append("")
            
            # Original article
            content.append("🇪🇸 ORIGINAL ARTICLE (SPANISH)")
            content.append("-" * 50)
            content.append(f"TITLE: {original_article.get('title', 'Not specified')}")
            content.append(f"LINK: {original_article.get('link', 'Not specified')}")
            content.append(f"SOURCE: {original_article.get('source', 'Not specified')}")
            content.append(f"DATE: {original_article.get('published_date', 'Not specified')}")
            content.append("")
            content.append("DESCRIPTION:")
            content.append(original_article.get('summary', 'Not specified'))
            content.append("")
            
            # Generated article
            if generated_article:
                content.append("🇷🇺 RUSSIAN ARTICLE")
                content.append("-" * 50)
                content.append(f"TITLE: {generated_article.get('title', 'Not specified')}")
                content.append("")
                content.append("CONTENT:")
                content.append(generated_article.get('content', 'Not specified'))
                content.append("")
                if generated_article.get('tags'):
                    content.append(f"TAGS: {', '.join(generated_article.get('tags', []))}")
                content.append("")
            
            # Metadata
            content.append("📊 METADATA")
            content.append("-" * 50)
            content.append(f"PRIORITY: {original_article.get('priority_score', 0)}")
            content.append(f"URGENT: {'Yes' if original_article.get('urgent', False) else 'No'}")
            content.append(f"CATEGORIES: {', '.join(original_article.get('categories', []))}")
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(content))
            
            return filepath
            
        except Exception as e:
            print(f"[article-generator] ⚠️  File save error: {e}")
            return None

    def generate_articles(self) -> Dict:
        """
        Generates articles from unprocessed news
        
        Returns:
            Dictionary with generation results
        """
        if not self._acquire_lock():
            return {
                'status': 'skipped',
                'reason': 'locked',
                'message': 'Another instance is already running'
            }
        
        try:
            print(f"[article-generator] 🔍 Searching for articles to generate...")
            
            # Get unprocessed articles
            articles_ref = self.db.collection('articles')
            articles_docs = list(articles_ref.limit(500).stream())
            
            # Filter articles
            articles = []
            for doc in articles_docs:
                data = doc.to_dict() or {}
                if (not data.get('published', False) and 
                    not data.get('exported_to_site', False) and 
                    data.get('processed', False)):
                    data['id'] = doc.id
                    articles.append(data)
            
            if not articles:
                print(f"[article-generator] ℹ️  No articles to generate")
                return {
                    'status': 'success',
                    'generated': 0,
                    'total': 0,
                    'message': 'No new articles to process'
                }
            
            # Limit batch size
            articles = articles[:self.config.batch_size]
            print(f"[article-generator] 📝 Generating {len(articles)} articles...")
            
            generated_count = 0
            errors = []
            
            for article in articles:
                try:
                    article_id = article['id']
                    
                    # Check required fields
                    title = article.get('title', '').strip()
                    summary = article.get('summary', '').strip()
                    link = article.get('link', '').strip()
                    
                    if not summary:
                        content = article.get('content', '').strip()
                        if content and len(content) > self.config.min_text_length:
                            summary = content[:200] + "..."
                        else:
                            print(f"[article-generator] ⚠️  Skipping {article_id}: no text")
                            continue
                    
                    if not title or not link:
                        print(f"[article-generator] ⚠️  Skipping {article_id}: missing title/link")
                        continue
                    
                    # Prepare data for generation
                    article_data = {
                        'title': title,
                        'summary': summary,
                        'link': link,
                        'content': article.get('content', summary),
                        'image': article.get('image', ''),
                        'priority_score': article.get('priority_score', 0),
                        'urgent': article.get('urgent', False),
                        'source_article_id': article_id
                    }
                    
                    # Generate article
                    generated_id = generate_article_from_news(article_data, self.firebase_client)
                    
                    if generated_id:
                        # Get generated article
                        generated_article = None
                        try:
                            gen_doc = self.db.collection('generated_articles').document(generated_id).get()
                            if gen_doc.exists:
                                generated_article = gen_doc.to_dict()
                        except Exception as e:
                            print(f"[article-generator] ⚠️  Could not retrieve article: {e}")
                        
                        # Save to file
                        if self.config.save_to_files:
                            filepath = self.save_article_to_file(article_id, article, generated_article)
                            if filepath:
                                print(f"[article-generator] 💾 Saved: {filepath}")
                        
                        # Mark as exported
                        self.db.collection('articles').document(article_id).update({
                            'exported_to_site': True,
                            'exported_at': datetime.now(timezone.utc).isoformat(),
                            'generated_article_id': generated_id
                        })
                        
                        generated_count += 1
                        print(f"[article-generator] ✅ Created article: {generated_id}")
                    
                except Exception as e:
                    error_msg = f"Error for {article.get('id', 'unknown')}: {str(e)}"
                    print(f"[article-generator] ❌ {error_msg}")
                    errors.append(error_msg)
            
            print(f"[article-generator] ✅ Processing completed: {generated_count}/{len(articles)}")
            
            return {
                'status': 'success',
                'generated': generated_count,
                'total': len(articles),
                'errors': errors,
                'message': f'Generated {generated_count} out of {len(articles)} articles',
                'instance_id': self.instance_id,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            print(f"[article-generator] ❌ Critical error: {e}")
            return {
                'status': 'error',
                'reason': 'processing_error',
                'message': str(e)
            }
        finally:
            self._release_lock()


def main():
    """Entry point for worker execution"""
    print("=" * 60)
    print("📝 Article Generator Worker - Article Generator")
    print("=" * 60)
    
    try:
        config = GeneratorConfig.from_env()
        worker = ArticleGeneratorWorker(config)
        result = worker.generate_articles()
        
        print("\n" + "=" * 60)
        print("📊 RESULTS")
        print("=" * 60)
        print(f"Status: {result['status']}")
        print(f"Generated: {result.get('generated', 0)}")
        print(f"Total processed: {result.get('total', 0)}")
        
        if result.get('errors'):
            print(f"\nErrors ({len(result['errors'])}):")
            for error in result['errors'][:5]:  # Show first 5
                print(f"  • {error}")
        
        exit_code = 0 if result['status'] == 'success' else 1
        sys.exit(exit_code)
        
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Critical error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
