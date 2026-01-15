import os
import logging
import requests
from io import BytesIO
from pathlib import Path
from typing import Optional
from PIL import Image
from openai import OpenAI


class ImageGenerator:
    """Generates images for articles using OpenAI DALL-E when image_url is missing."""
    
    def __init__(self, model: str = "gpt-image-1.5", images_dir: Optional[Path] = None):
        """
        Initialize image generator.
        
        Args:
            model: Image model to use (gpt-image-1.5, dall-e-2, or dall-e-3)
            images_dir: Directory to save generated images (default: project_root/images)
        """
        self.model = model
        self.logger = logging.getLogger('workers.article_generator.image_generator')
        self.logger.propagate = True
        
        # Initialize OpenAI client (Azure or OpenAI)
        azure_dalle_endpoint = os.getenv('AZURE_DALLE_ENDPOINT')
        azure_dalle_key = os.getenv('AZURE_DALLE_KEY')
        
        if azure_dalle_endpoint and azure_dalle_key:
            # Use Azure DALL-E
            self.logger.info('Using Azure DALL-E endpoint')
            self.use_azure = True
            self.azure_endpoint = azure_dalle_endpoint
            self.azure_key = azure_dalle_key
            self.client = None  # Will use REST API directly
        else:
            # Use OpenAI
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                raise RuntimeError('OPENAI_API_KEY or Azure DALL-E credentials required')
            self.logger.info('Using OpenAI DALL-E')
            self.use_azure = False
            self.client = OpenAI(api_key=api_key)
        
        # Set up images directory
        if images_dir is None:
            # Default to project_root/public/images/news
            project_root = Path(__file__).resolve().parent.parent.parent
            images_dir = project_root / 'public' / 'images' / 'news'
        self.images_dir = Path(images_dir)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        
    def _create_image_prompt(self, title: str, description: str, content: str) -> str:
        """
        Create a concise image generation prompt from article content.
        
        Args:
            title: Article title
            description: Article description
            content: Article content (first 500 chars used)
            
        Returns:
            Image generation prompt
        """
        # Use GPT to create a visual prompt based on article content
        try:
            system_prompt = """You are an expert at creating image generation prompts for news articles.
Create a concise, visual prompt for DALL-E that captures the essence of the article.
The prompt should:
- Be 1-2 sentences maximum
- Focus on visual elements and atmosphere
- Be appropriate for news/editorial content
- Avoid text in the image
- Use clear, descriptive language

Return ONLY the image prompt, nothing else."""

            content_excerpt = content[:500] if content else description
            
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Title: {title}\n\nDescription: {description}\n\nContent: {content_excerpt}\n\nGenerate image prompt:"}
                ],
                max_tokens=150,
                temperature=0.7
            )
            
            prompt = response.choices[0].message.content.strip()
            self.logger.info(f'Created image prompt: {prompt[:100]}...')
            return prompt
            
        except Exception as e:
            self.logger.warning(f'Failed to create AI prompt, using fallback: {e}')
            # Fallback: simple combination of title and description
            return f"Editorial illustration representing: {title}. {description[:100]}"
    
    def _generate_with_azure_dalle(self, prompt: str) -> Optional[str]:
        """
        Generate image using Azure DALL-E REST API.
        
        Args:
            prompt: Image generation prompt
            
        Returns:
            Image URL or None if failed
        """
        try:
            headers = {
                "api-key": self.azure_key,
                "Content-Type": "application/json"
            }
            
            payload = {
                "prompt": prompt,
                "size": "1792x1024",
                "quality": "standard",
                "n": 1
            }
            
            self.logger.info(f'Calling Azure DALL-E: {self.azure_endpoint[:80]}...')
            response = requests.post(
                self.azure_endpoint,
                json=payload,
                headers=headers,
                timeout=120  # Image generation can take time
            )
            
            response.raise_for_status()
            data = response.json()
            
            # Azure returns data in same format as OpenAI
            if data.get('data') and len(data['data']) > 0:
                image_url = data['data'][0].get('url')
                self.logger.info(f'✅ Successfully generated image via Azure DALL-E')
                return image_url
            
            self.logger.warning('Azure DALL-E returned no image data')
            return None
            
        except Exception as e:
            self.logger.exception(f'Azure DALL-E call failed: {e}')
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
        
        # Resize to standard 16:9 resolution (1792x1008 for high quality)
        img = img.resize((1792, 1008), Image.Resampling.LANCZOS)
        self.logger.info(f'Cropped/resized image to 16:9 (1792x1008)')
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
            # Download image
            response = requests.get(image_url, timeout=30)
            response.raise_for_status()
            
            # Convert to JPEG using PIL (handles PNG transparency)
            img = Image.open(BytesIO(response.content))
            
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
            
            # Save as JPEG
            filename = f"{doc_id}.jpg"
            file_path = self.images_dir / filename
            img.save(file_path, 'JPEG', quality=90, optimize=True)
            
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
        existing_image_url: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate an image for an article if no image exists.
        
        Args:
            doc_id: Document ID
            title: Article title
            description: Article description  
            content: Article content
            existing_image_url: Existing image URL (if any)
            
        Returns:
            Image URL (existing or newly generated) or None
        """
        # Return existing image if present
        if existing_image_url and existing_image_url.strip():
            self.logger.debug(f'Using existing image for {doc_id}')
            return existing_image_url
        
        self.logger.info(f'No image found for {doc_id}, generating new image...')
        
        try:
            # Create prompt based on content
            image_prompt = self._create_image_prompt(title, description, content)
            
            # Generate image using DALL-E (supports dall-e-2, dall-e-3, gpt-image-1.5)
            self.logger.info(f'Generating image with {self.model} for {doc_id}...')
            
            # Use Azure REST API if configured
            if self.use_azure:
                image_url = self._generate_with_azure_dalle(image_prompt)
                if not image_url:
                    return None
            else:
                # Use OpenAI SDK
                # Configure parameters based on model
                if self.model == "dall-e-3":
                    # DALL-E 3 supports: 1024x1024, 1792x1024, 1024x1792
                    # quality: "standard" or "hd"
                    response = self.client.images.generate(
                        model=self.model,
                        prompt=image_prompt,
                        size="1792x1024",  # Wide format (16:9 similar)
                        quality="standard",
                        n=1,
                    )
                elif self.model == "dall-e-2":
                    # DALL-E 2 supports: 256x256, 512x512, 1024x1024
                    response = self.client.images.generate(
                        model=self.model,
                        prompt=image_prompt,
                        size="1024x1024",
                        n=1,
                    )
                else:
                    # GPT Image 1.5 or other models - use auto sizing
                    response = self.client.images.generate(
                        model=self.model,
                        prompt=image_prompt,
                        size="auto",
                        quality="low",
                        n=1,
                    )
                
                if not (response.data and len(response.data) > 0):
                    self.logger.warning(f'No image data returned for {doc_id}')
                    return None
                
                image_url = response.data[0].url
                self.logger.info(f'✅ Successfully generated image via OpenAI')
            
            # Download and save image locally
            self.logger.info(f'Downloading generated image...')
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
