import base64
import os
import logging
import requests
import time
from io import BytesIO
from pathlib import Path
from typing import Optional
from PIL import Image
import json
from workers.tools.openai_client import (
    get_openai_client,
    chat_completion,
    get_openrouter_api_key,
    get_gemini_api_key,
    is_gemini_enabled,
    is_openrouter_client,
    resolve_model_name,
    OPENROUTER_FREE_IMAGE_MODEL,
    GEMINI_FREE_IMAGE_MODEL,
)


class ImageGenerator:
    """Generates images for articles when image_url is missing."""

    def __init__(self, model: str = "dall-e-3", images_dir: Optional[Path] = None):
        """
        Initialize image generator.

        Args:
            model: Image model to use (legacy OpenAI names are auto-mapped)
            images_dir: Directory to save generated images (default: project_root/images)
        """
        self.model = model
        self.logger = logging.getLogger('workers.article_generator.image_generator')
        self.logger.propagate = True

        self.client = get_openai_client()
        if not self.client:
            raise RuntimeError(
                'No LLM image provider configured. Set GEMINI_API_KEY, OR_API_KEY or OPENAI_API_KEY'
            )
        
        # Set up images directory
        if images_dir is None:
            # Default to project_root/public/images/news
            project_root = Path(__file__).resolve().parent.parent.parent
            images_dir = project_root / 'public' / 'images' / 'news'
        self.images_dir = Path(images_dir)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        
    def _save_raw_prompt(self, doc_id: str, stage: str, content: str) -> None:
        """Log raw prompt/response for image generation."""
        try:
            self.logger.warning(f'Raw {stage} for image generation {doc_id}:\n{content[:2000]}')
            
            if os.environ.get('GITHUB_ACTIONS', '').lower() == 'true':
                log_dir = Path(os.environ.get('GITHUB_WORKSPACE', os.getcwd())) / 'logs' / 'openai_raw'
                log_dir.mkdir(parents=True, exist_ok=True)
                fname = log_dir / f"{doc_id}_image_{stage}_{int(time.time())}.txt"
                fname.write_text(content or '', encoding='utf-8')
                self.logger.warning(f'Wrote CI raw output to {fname}')
        except Exception as e:
            self.logger.debug(f'Failed to save raw prompt: {e}')
        
    def _create_image_prompt(self, doc_id: str, title: str, description: str, content: str) -> Optional[str]:
        """
        Create a concise image generation prompt from article content.
        
        Args:
            doc_id: Document ID for logging
            title: Article title
            description: Article description
            content: Article content
            
        Returns:
            Image generation prompt for DALL-E
        """
        # Use GPT-4o-mini to create a specialized prompt for DALL-E 3
        try:
            system_prompt = """
You are an automated prompt generator for DALL·E 3,
creating realistic, policy-safe editorial photographs for news websites.

INPUT: a news article.
OUTPUT: ONE final image prompt in English.
Return ONLY the image prompt.

GOAL:
Create a believable editorial photograph that feels real,
varied, and non-repetitive, without visual artifacts or policy violations.

GENERAL CONSTRAINTS (ALWAYS):

- Photographic realism is mandatory.
- No illustration, no CGI look, no concept art.
- No text, logos, or readable signage.
- No real politicians or recognizable public figures.
- No depiction of real crimes, disasters, or violent events as factual photos.

STEP 1 — INTERNAL CLASSIFICATION:
Determine whether the article is soft or hard news.

STEP 2 — SELECT ONE VISUAL APPROACH (choose ONLY ONE per image):
A) Environment-first scene (space without people)
B) Close-up of a relevant object or surface detail
C) Partial human presence (hands, reflection, silhouette, cropped figure)
D) Single anonymous person in a natural, non-heroic moment
E) Contextual action captured mid-moment (minimal movement, unposed)

Never repeat the same approach systematically across articles.

STEP 3 — SCENE RULES:
- The scene must be realistic and ordinary.
- Avoid symbolic or metaphorical visuals.
- Avoid perfect symmetry or staged composition.
- Include ONE subtle imperfection or visual tension.

STEP 4 — PHOTOGRAPHIC STYLE (MANDATORY):
- editorial daylight photography
- neutral or slightly uneven lighting
- realistic white balance
- muted but natural color palette
- imperfect framing
- natural depth of field
- subtle lens imperfections

STEP 5 — CAMERA ANCHORS (include at least two):
- 35mm or 50mm documentary photography
- full-frame DSLR look
- natural lens distortion
- realistic color grading (not stylized)

STEP 6 — PEOPLE (if present):
- anonymous only
- no clear or multiple faces
- no posing or heroic stance

FOR HARD NEWS ONLY:
- Do not depict the event itself.
- Show context, space, aftermath, or environment instead.

End the prompt with:
"No text, no illustration, no cinematic style, no surreal elements."

ARTICLE:
[ARTICLE]
"""
            
            # Combine article information
            article_text = f"Title: {title}\n\nDescription: {description}\n\nContent:\n{content}"
            user_prompt = f"[ARTICLE]\n\n{article_text}"
            
            # Log system and user prompts
            self._save_raw_prompt(doc_id, 'system_prompt', system_prompt)
            self._save_raw_prompt(doc_id, 'user_prompt', user_prompt)
            
            
            response = chat_completion(
                client=get_openai_client(),
                model="gpt-5.4-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=400,
            )
            
            # chat_completion returns the content string directly
            if not response:
                self.logger.error(f'No response received for {doc_id}')
                return None
                
            response_text = response.strip()
            
            # Log GPT response
            self._save_raw_prompt(doc_id, 'gpt_response', response_text)
            
            # Response should be the prompt directly, no JSON parsing needed
            prompt = response_text.strip()
            
            if not prompt:
                self.logger.error(f'Empty prompt received for {doc_id}')
                return None

            self.logger.info(f'Created image prompt for {doc_id}')
            self.logger.info(f'Prompt: {prompt[:200]}...' if len(prompt) > 200 else f'Prompt: {prompt}')
            return prompt
            
        except Exception as e:
            self.logger.error(f'Failed to create AI prompt: {e}')
            return None
    
    def _generate_image_via_openrouter(self, prompt: str) -> Optional[str]:
        """Generate an image through OpenRouter's chat completions endpoint."""
        model = resolve_model_name(self.model, provider='openrouter')
        if not model or OPENROUTER_FREE_IMAGE_MODEL is None:
            self.logger.warning('OpenRouter free-only mode has no image generation model available; skipping image generation')
            return None
        base_url = (os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')).rstrip('/')
        api_key = get_openrouter_api_key()
        if not api_key:
            self.logger.error('OR_API_KEY not configured')
            return None

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        referer = os.getenv('OPENROUTER_APP_URL') or os.getenv('OPENROUTER_HTTP_REFERER')
        title = os.getenv('OPENROUTER_APP_TITLE') or os.getenv('OPENROUTER_X_TITLE')
        if referer:
            headers['HTTP-Referer'] = referer
        if title:
            headers['X-Title'] = title

        payload = {
            'model': model,
            'messages': [
                {'role': 'user', 'content': prompt},
            ],
            'modalities': ['image', 'text'],
            'stream': False,
            'image_config': {
                'aspect_ratio': '16:9',
            },
        }

        try:
            self.logger.info(f'Calling OpenRouter image generation with model={model}')
            response = requests.post(
                f'{base_url}/chat/completions',
                headers=headers,
                json=payload,
                timeout=180,
            )
            response.raise_for_status()
            data = response.json()
            choices = data.get('choices') or []
            if not choices:
                self.logger.warning('OpenRouter image generation returned no choices')
                return None

            message = (choices[0] or {}).get('message') or {}
            images = message.get('images') or []
            if not images:
                self.logger.warning('OpenRouter image generation returned no images')
                return None

            image = images[0] or {}
            image_url = (
                ((image.get('image_url') or {}).get('url'))
                or ((image.get('imageUrl') or {}).get('url'))
                or image.get('url')
            )
            if image_url:
                self.logger.info('Successfully generated image via OpenRouter')
                return image_url

            self.logger.warning('OpenRouter image generation returned an image without URL payload')
            return None
        except Exception as e:
            self.logger.exception(f'OpenRouter image generation failed: {e}')
            return None

    def _generate_image_via_gemini(self, prompt: str) -> Optional[str]:
        """Generate an image through Google AI Studio's generateContent endpoint.

        Returns a data: URL, which _download_and_save_image already handles.
        """
        api_key = get_gemini_api_key()
        if not api_key:
            self.logger.error('GEMINI_API_KEY not configured')
            return None

        model = resolve_model_name(self.model, provider='gemini') or GEMINI_FREE_IMAGE_MODEL
        if not model:
            self.logger.warning('No Gemini image model available; skipping image generation')
            return None

        url = (
            'https://generativelanguage.googleapis.com/v1beta/models/'
            f'{model}:generateContent'
        )
        payload = {
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {'responseModalities': ['IMAGE']},
        }

        try:
            self.logger.info(f'Calling Gemini image generation with model={model}')
            response = requests.post(
                url,
                headers={'Content-Type': 'application/json', 'x-goog-api-key': api_key},
                json=payload,
                timeout=180,
            )
            if response.status_code == 429:
                self.logger.warning('Gemini image quota exhausted (429); skipping image generation')
                return None
            response.raise_for_status()
            data = response.json()

            for candidate in data.get('candidates') or []:
                parts = ((candidate or {}).get('content') or {}).get('parts') or []
                for part in parts:
                    inline = part.get('inlineData') or part.get('inline_data')
                    if not inline:
                        continue
                    b64 = inline.get('data')
                    if b64:
                        mime = inline.get('mimeType') or inline.get('mime_type') or 'image/png'
                        self.logger.info('Successfully generated image via Gemini')
                        return f'data:{mime};base64,{b64}'

            self.logger.warning('Gemini image generation returned no inline image data')
            return None
        except Exception as e:
            self.logger.exception(f'Gemini image generation failed: {e}')
            return None

    def _generate_image(self, prompt: str) -> Optional[str]:
        """
        Generate image using the configured provider.

        Args:
            prompt: Image generation prompt

        Returns:
            Image URL or None if failed
        """
        try:
            if is_openrouter_client(self.client):
                return self._generate_image_via_openrouter(prompt)

            if is_gemini_enabled():
                return self._generate_image_via_gemini(prompt)

            self.logger.info(f'Calling OpenAI image generation with model={self.model}')
            if self.model == "dall-e-3":
                response = self.client.images.generate(
                    model=self.model,
                    prompt=prompt,
                    size="1792x1024",
                    quality="standard",
                    n=1,
                )
            elif self.model == "dall-e-2":
                response = self.client.images.generate(
                    model=self.model,
                    prompt=prompt,
                    size="1024x1024",
                    n=1,
                )
            else:
                response = self.client.images.generate(
                    model=self.model,
                    prompt=prompt,
                    size="auto",
                    quality="low",
                    n=1,
                )

            if response.data and len(response.data) > 0:
                image_url = response.data[0].url
                self.logger.info('Successfully generated image via OpenAI')
                return image_url

            self.logger.warning('OpenAI image generation returned no data')
            return None

        except Exception as e:
            self.logger.exception(f'OpenAI image generation failed: {e}')
            return None
    
    def _crop_to_16_9(self, img: Image.Image) -> Image.Image:
        """
        Crop or resize image to 16:9 aspect ratio.
        
        Args:
            img: PIL Image to process
            
        Returns:
            Image with 16:9 aspect ratio
        """
        width, height = img.size
        target_ratio = 16 / 9
        current_ratio = width / height
        
        if abs(current_ratio - target_ratio) < 0.01:
            # Already close to 16:9
            return img
        
        if current_ratio > target_ratio:
            # Image is wider, crop width
            new_width = int(height * target_ratio)
            left = (width - new_width) // 2
            img = img.crop((left, 0, left + new_width, height))
        else:
            # Image is taller, crop height
            new_height = int(width / target_ratio)
            top = (height - new_height) // 2
            img = img.crop((0, top, width, top + new_height))
        
        # Resize to standard 16:9 resolution (960x540 for optimal file size ~60-80kb)
        img = img.resize((960, 540), Image.Resampling.LANCZOS)
        self.logger.info(f'Cropped/resized image to 16:9 (960x540)')
        return img
    
    def _download_and_save_image(self, image_url: str, doc_id: str) -> Optional[str]:
        """
        Download image from URL and save to images directory as JPEG.
        
        Args:
            image_url: URL of the generated image
            doc_id: Document ID for filename
            
        Returns:
            Relative path to saved image (e.g., 'images/doc_id.jpg') or None if failed
        """
        try:
            if image_url.startswith('data:'):
                _, encoded = image_url.split(',', 1)
                image_bytes = base64.b64decode(encoded)
            else:
                response = requests.get(image_url, timeout=30)
                response.raise_for_status()
                image_bytes = response.content

            # Convert to JPEG using PIL (handles PNG transparency)
            img = Image.open(BytesIO(image_bytes))
            
            # Convert RGBA to RGB if necessary (JPEG doesn't support transparency)
            if img.mode in ('RGBA', 'LA', 'P'):
                # Create white background
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Crop/resize to 16:9 aspect ratio
            img = self._crop_to_16_9(img)
            
            # Save as JPEG with optimized quality for ~80-100kb file size
            filename = f"{doc_id}.jpg"
            file_path = self.images_dir / filename
            img.save(file_path, 'JPEG', quality=75, optimize=True)
            
            # Return relative path from project root
            relative_path = f"public/images/news/{filename}"
            self.logger.info(f'Saved image to {relative_path}')
            return relative_path
            
        except Exception as e:
            self.logger.exception(f'Failed to download and save image: {e}')
            return None
    
    def generate_image_for_article(
        self, 
        doc_id: str,
        title: str, 
        description: str, 
        content: str,
        existing_image_url: Optional[str] = None,
        *,
        save_locally: bool = True
    ) -> Optional[str]:
        """
        Generate an image for an article if no image exists.
        
        Args:
            doc_id: Document ID
            title: Article title
            description: Article description  
            content: Article content
            existing_image_url: Existing image URL (if any)
            save_locally: Persist the generated image locally when True; return provider URL otherwise
            
        Returns:
            Image URL (newly generated) or None
        """
        self.logger.info(f'Generating new image for {doc_id} (ignoring existing_image_url)...')
        
        try:
            # Create prompt based on content
            image_prompt = self._create_image_prompt(doc_id, title, description, content)
            
            if not image_prompt:
                self.logger.error(f'Failed to create image prompt for {doc_id}')
                return None
            
            # Log final prompt that will be sent to DALL-E
            self._save_raw_prompt(doc_id, 'dalle_prompt', image_prompt)
            
            self.logger.info(f'Generating image with {self.model} for {doc_id}...')
            image_url = self._generate_image(image_prompt)
            if not image_url:
                return None
            
            if not save_locally:
                self.logger.info(f'Skipping local persistence for {doc_id}, returning provider URL')
                return image_url

            self.logger.info(f'Downloading generated image...')
            # Download and save image locally
            local_path = self._download_and_save_image(image_url, doc_id)
            if local_path:
                # Return absolute URL for ke-pasa.es domain
                web_url = f'https://ke-pasa.es/images/news/{doc_id}.jpg'
                self.logger.info(f'✅ Image saved locally, public URL: {web_url}')
                return web_url
            else:
                # Fallback to URL if download failed
                self.logger.warning(f'Failed to save image locally, using URL: {image_url}')
                return image_url
            
        except Exception as e:
            self.logger.exception(f'Failed to generate image for {doc_id}: {e}')
            return None
