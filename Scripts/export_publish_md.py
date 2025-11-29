import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import re
import unicodedata

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except Exception as e:
    print('Missing firebase_admin package. Install with: pip install firebase-admin')
    raise


def slugify_title(title: str, maxlen: int = 100) -> str:
    if not title:
        return 'article'
    title = title.lower().strip()
    tbl = {
        'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z','и':'i','й':'j',
        'к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f',
        'х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'shch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'
    }
    out = []
    for ch in title:
        if ch in tbl:
            out.append(tbl[ch])
        elif 'a' <= ch <= 'z' or ch.isdigit():
            out.append(ch)
        elif ch.isspace() or ch in ['-', '_']:
            out.append('_')
        else:
            decomp = unicodedata.normalize('NFKD', ch)
            ascii_part = ''.join(c for c in decomp if ord(c) < 128)
            if ascii_part:
                ascii_part = re.sub(r'[^a-z0-9]', '_', ascii_part.lower())
                out.append(ascii_part)
            else:
                out.append('_')
    slug = re.sub(r'_+', '_', ''.join(out)).strip('_')
    slug = slug[:maxlen]
    return slug or 'article'


def normalize_publish_md(publish_md: str, image_url: str | None = None) -> str:
    """Normalize markdown frontmatter:
    - collapse multi-line image entries (including escaped quotes) to `image: "<url>"`
    - if image missing and image_url provided, insert it
    - ensure title, description, keywords are quoted
    Returns normalized markdown text.
    """
    try:
        m = re.match(r'(?s)^(---\s*(.*?)\s*---\s*)(.*)$', publish_md)
        if not m:
            # no frontmatter; optionally prepend image
            if image_url and not re.search(r'(?m)^\s*image:\s*\S', publish_md):
                return f'---\nimage: "{image_url}"\n---\n' + publish_md
            return publish_md

        fm = m.group(2)
        body = m.group(3)

        # fix multi-line image: \n"url" and escaped quotes
        def fix_image_block(match):
            url = match.group(1)
            url = url.replace('\\', '').strip().strip('"\'"')
            return f'image: "{url}"'

        fm = re.sub(r'(?m)^image:\s*$\n^[\\\"\']*(https?://\S+)[\\\"\']*\s*$', fix_image_block, fm, flags=re.MULTILINE)

        # If image_url provided, prefer it when image is missing or empty
        if image_url:
            if re.search(r'(?m)^\s*image:\s*$', fm) or not re.search(r'(?m)^\s*image:\s*\S', fm):
                # insert or replace image
                if re.search(r'(?m)^\s*image:\s*\S', fm):
                    fm = re.sub(r'(?m)^(image:\s*)(["\']?)(.*?)(["\']?)\s*$', lambda mo: f'image: "{image_url}"', fm)
                else:
                    fm = fm.strip() + f"\nimage: \"{image_url}\"\n"

        # Normalize existing image values by removing backslashes inside quotes
        fm = re.sub(r'(?m)^(image:\s*)(["\']?)(.*?)\2\s*$', lambda mo: f'image: "{mo.group(3).replace("\\\\","")}"', fm)

        # Ensure title, description, keywords are quoted
        def quote_field(fm_text, name):
            def repl(mo):
                val = (mo.group(1) or mo.group(2) or '').strip()
                val = val.replace('"', '\\"')
                return f'{name}: "{val}"'
            # matches either quoted or unquoted value after `name:`
            return re.sub(rf'(?m)^{name}:\s*(?:"(.*?)"|(.*?))\s*$', lambda mo: repl(mo), fm_text)

        for fld in ('title', 'description', 'keywords'):
            try:
                fm = quote_field(fm, fld)
            except Exception:
                pass

        new_md = '---\n' + fm.strip() + '\n---\n' + body
        return new_md
    except Exception:
        return publish_md
 


def main(key_path: str = 'firebase_key.json', out_dir: str = 'articles'):
    key_file = Path(key_path)
    if not key_file.exists():
        print(f'Key file not found: {key_file.resolve()}')
        sys.exit(2)

    try:
        cred = credentials.Certificate(str(key_file))
        try:
            firebase_admin.initialize_app(cred)
        except Exception:
            # app may already be initialized in some environments
            pass
        db = firestore.client()
    except Exception as e:
        print('Failed to initialize Firestore client:', e)
        raise

    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    written = 0
    total_seen = 0

    # Prefer server-side filtering for performance. Many records use ISO8601 strings for created_at,
    # so compare as strings. If that fails (e.g., field type mismatch or missing index), fall back to
    # streaming the collection and applying the cutoff locally.
    cutoff_iso = cutoff.isoformat()
    try:
        query = db.collection('articles_ru').where('total_score', '>=', 60).where('created_at', '>=', cutoff_iso)
        docs = list(query.stream())
    except Exception as e:
        print('Server-side filtered query failed, falling back to client-side filter:', e)
        try:
            docs = list(db.collection('articles_ru').stream())
        except Exception as e2:
            print('Failed to stream articles_ru collection:', e2)
            raise

    for doc in docs:
        total_seen += 1
        data = doc.to_dict() or {}
        created = data.get('created_at') or data.get('updated_at')
        created_dt = None
        if isinstance(created, str):
            try:
                created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
            except Exception:
                created_dt = None
        elif isinstance(created, datetime):
            created_dt = created

        if created_dt is None:
            # If Firestore returns Timestamp objects, they may be timezone-aware already
            # try to read as attribute
            try:
                # some Firestore libs return protobuf Timestamp-like
                if hasattr(created, 'to_datetime'):
                    created_dt = created.to_datetime()
            except Exception:
                created_dt = None

        if created_dt is None:
            # skip if no reliable timestamp
            continue

        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)

        if created_dt < cutoff:
            continue

        publish_md = data.get('publish_md')
        if not publish_md:
            continue
        # Extract slug from publish_md frontmatter if present
        slug = None
        try:
            fm_match = re.match(r'(?s)^---\s*(.*?)\s*---\s*(.*)$', publish_md)
            fm = None
            body = publish_md
            if fm_match:
                fm = fm_match.group(1)
                body = fm_match.group(2)
                # look for slug in frontmatter
                m = re.search(r'(?m)^slug:\s*["\']?([^"\'\n]+)["\']?\s*$', fm)
                if m:
                    slug = m.group(1).strip()
        except Exception:
            slug = None

        # Fallback to transliterated title
        if not slug:
            title_ru = data.get('title_ru') or data.get('title') or 'article'
            slug = slugify_title(title_ru)

        # Normalize frontmatter: quote title/description/keywords and fix image entries
        try:
            image_url = (data.get('image_url') or data.get('image') or '').strip()

            if fm is not None:
                orig_fm = fm

                # Fix multi-line image entries like: image:\n\"https://...\"
                def fix_image(mobj):
                    # mobj may capture the URL with optional escaped quotes
                    url = mobj.group(1)
                    # remove any leading/trailing backslashes or quotes
                    url = url.replace('\\', '').strip().strip('"\'"')
                    return f'image: "{url}"'

                # Replace occurrences where image is on its own line and URL on next
                fm = re.sub(r'(?m)^image:\s*$\n^[\\\"\']*(https?://\S+)[\\\"\']*\s*$', fix_image, fm, flags=re.MULTILINE)

                # Replace any image: somevalue (possibly empty) with quoted image_url if empty
                if image_url:
                    # If image key exists but is empty or not a valid URL, replace it
                    fm = re.sub(r'(?m)^(image:\s*)(["\']?)(.*?)(["\']?)\s*$', lambda mo: f'image: "{image_url}"', fm)
                else:
                    # If image key exists with a valid URL, ensure it's quoted and remove backslashes
                    fm = re.sub(r'(?m)^(image:\s*)(["\']?)(.*?)\2\s*$', lambda mo: f'image: "{mo.group(3).replace("\\\\","")}"', fm)

                # Ensure title/description/keywords are quoted
                def quote_field(fm_text, name):
                    def repl(m):
                        val = m.group(2).strip()
                        val = val.replace('"', '\\"')
                        return f'{name}: "{val}"'
                    return re.sub(rf'(?m)^{name}:\s*["\']?(.*?)["\']?\s*$', repl, fm_text)

                for fld in ('title', 'description', 'keywords'):
                    try:
                        fm = quote_field(fm, fld)
                    except Exception:
                        pass

                # Rebuild publish_md
                publish_md = '---\n' + fm.strip() + '\n---\n' + body
            else:
                # no frontmatter: prepend minimal frontmatter with image if available
                if image_url and not re.search(r'(?m)^\s*image:\s*\S', publish_md):
                    publish_md = f'---\nimage: "{image_url}"\n---\n' + publish_md
        except Exception:
            pass

        # Normalize publish_md frontmatter before writing
        try:
            image_url_doc = (data.get('image_url') or data.get('image') or '').strip()
            publish_md = normalize_publish_md(publish_md, image_url_doc)
        except Exception:
            pass

        filename = f"{slug}_{doc.id}.md"
        fp = out_path / filename
        try:
            with open(fp, 'w', encoding='utf-8') as fh:
                fh.write(publish_md)
            written += 1
            print(f'Wrote: {fp} ({fp.stat().st_size} bytes)')
        except Exception as e:
            print(f'Failed to write file for {doc.id}:', e)

    print(f'Done. Seen {total_seen} docs, wrote {written} files to {out_path}')
    return written


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--key', '-k', default='firebase_key.json', help='Path to service account JSON')
    p.add_argument('--out', '-o', default='articles', help='Output directory')
    args = p.parse_args()
    main(args.key, args.out)
