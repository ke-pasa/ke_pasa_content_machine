"""
Video Generator using MoviePy
Combines image + audio to create news videos
"""

import os
import logging
import tempfile
from typing import Tuple, Optional
from pathlib import Path

_logger = logging.getLogger('workers.tools.video_generator')


class VideoGenerator:
    """Generate video from image + audio using MoviePy"""
    
    def __init__(self):
        try:
            from moviepy.editor import ImageClip, AudioFileClip, CompositeVideoClip
            self.moviepy_available = True
            _logger.info("VideoGenerator initialized with MoviePy")
        except ImportError as e:
            self.moviepy_available = False
            raise ValueError(f"MoviePy not available: {e}. Please install moviepy to generate videos.")
    
    def generate_video(self, image_url: str, audio_path: str, output_path: str, 
                      duration: Optional[float] = None) -> Tuple[bool, Optional[str]]:
        """
        Generate video from image and audio using MoviePy
        
        Args:
            image_url: URL or local path to image
            audio_path: Path to audio file
            output_path: Output video file path
            duration: Video duration (auto-detect from audio if None)
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            from moviepy.editor import ImageClip, AudioFileClip, CompositeVideoClip
            
            # Create output directory
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Download image if it's a URL
            temp_image = None
            if image_url.startswith(('http://', 'https://')):
                temp_image = self._download_image(image_url)
                if not temp_image:
                    return False, "Failed to download image"
                image_input = temp_image
            else:
                image_input = image_url
            
            # Verify files exist
            if not os.path.exists(image_input):
                return False, f"Image file not found: {image_input}"
            if not os.path.exists(audio_path):
                return False, f"Audio file not found: {audio_path}"
            
            _logger.info(f"Creating video with MoviePy: {image_input} + {audio_path} -> {output_path}")
            
            # Load audio to get duration
            audio_clip = AudioFileClip(audio_path)
            video_duration = duration or audio_clip.duration
            
            # Create image clip with audio duration
            image_clip = ImageClip(image_input).set_duration(video_duration)
            
            # Set video properties for better compatibility (skip resize to avoid PIL issues)
            # image_clip = image_clip.resize(height=720)  # HD resolution
            
            # Combine image and audio
            video_clip = image_clip.set_audio(audio_clip)
            
            # Write video file
            video_clip.write_videofile(
                output_path,
                fps=24,                    # 24 FPS for smoother video
                codec='libx264',           # H.264 codec for compatibility
                audio_codec='mp3',         # MP3 audio for better compatibility
                remove_temp=True,
                verbose=False,             # Reduce MoviePy logging
                logger=None               # Disable MoviePy logger
            )
            
            # Clean up clips
            video_clip.close()
            audio_clip.close()
            image_clip.close()
            
            # Clean up temporary image
            if temp_image and os.path.exists(temp_image):
                os.unlink(temp_image)
            
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                _logger.info(f"Video generation successful: {output_path} ({file_size} bytes)")
                return True, None
            else:
                return False, "Video file was not created"
                
        except Exception as e:
            error_msg = f"MoviePy video generation error: {str(e)}"
            _logger.exception(error_msg)
            return False, error_msg

    def generate_video_with_multiple_images(self, image_urls: list, audio_path: str, output_path: str) -> Tuple[bool, Optional[str]]:
        """
        Generate video with multiple images that change throughout the audio duration
        
        Args:
            image_urls: List of image URLs or local paths
            audio_path: Path to audio file
            output_path: Output video file path
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            from moviepy.editor import ImageClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips
            
            if not image_urls:
                return False, "No image URLs provided"
                
            # Create output directory
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Load audio to get duration
            audio_clip = AudioFileClip(audio_path)
            total_duration = audio_clip.duration
            
            # Calculate duration per image
            image_duration = total_duration / len(image_urls)
            
            _logger.info(f"Creating video with {len(image_urls)} images, {image_duration:.1f}s each, total: {total_duration:.1f}s")
            
            # Download all images and create clips
            video_clips = []
            temp_images = []
            
            for i, image_url in enumerate(image_urls):
                try:
                    # Download image if it's a URL
                    if image_url.startswith(('http://', 'https://')):
                        temp_image = self._download_image(image_url)
                        if not temp_image:
                            _logger.warning(f"Failed to download image {i+1}, skipping")
                            continue
                        temp_images.append(temp_image)
                        image_path = temp_image
                    else:
                        image_path = image_url
                    
                    # Create image clip - use original vertical images from Pexels
                    image_clip = ImageClip(image_path, duration=image_duration)
                    
                    video_clips.append(image_clip)
                    _logger.info(f"Added image {i+1}/{len(image_urls)}: {image_path}")
                    
                except Exception as e:
                    _logger.warning(f"Failed to process image {i+1}: {e}")
                    continue
            
            if not video_clips:
                return False, "No valid images could be processed"
            
            # Concatenate all video clips
            final_video = concatenate_videoclips(video_clips, method="compose")
            final_video = final_video.set_audio(audio_clip)
            
            # Write video
            _logger.info(f"Rendering video to {output_path}...")
            final_video.write_videofile(
                output_path,
                fps=24,
                codec='libx264',
                audio_codec='mp3',
                remove_temp=True,
                verbose=False,
                logger=None
            )
            
            # Clean up
            for clip in video_clips:
                clip.close()
            final_video.close()
            audio_clip.close()
            
            # Clean up temporary images
            for temp_image in temp_images:
                if os.path.exists(temp_image):
                    os.unlink(temp_image)
            
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                _logger.info(f"Multi-image video generation successful: {output_path} ({file_size} bytes)")
                return True, None
            else:
                return False, "Video file was not created"
                
        except Exception as e:
            error_msg = f"Multi-image video generation error: {str(e)}"
            _logger.exception(error_msg)
            return False, error_msg
    
    def generate_video_with_multiple_videos(self, video_urls: list, audio_path: str, output_path: str, title: str = "", audio_duration: float = None) -> Tuple[bool, Optional[str]]:
        """
        Generate video with multiple Pexels videos combined with audio and title overlay
        
        Args:
            video_urls: List of video URLs from Pexels
            audio_path: Path to audio file
            output_path: Output video file path
            title: Article title for text overlay
            audio_duration: Duration of audio (optional, will be calculated from file if not provided)
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips, TextClip, CompositeVideoClip
            
            if not video_urls:
                return False, "No video URLs provided"
                
            # Create output directory
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Load audio to get duration (or use provided duration)
            audio_clip = AudioFileClip(audio_path)
            if audio_duration is not None:
                total_duration = audio_duration
            else:
                total_duration = audio_clip.duration
            
            # Calculate duration per video
            video_duration = total_duration / len(video_urls)
            
            _logger.info(f"Creating video with {len(video_urls)} Pexels videos, {video_duration:.1f}s each, total: {total_duration:.1f}s")
            
            # Download all videos and create clips
            video_clips = []
            temp_videos = []
            
            try:
                for i, video_url in enumerate(video_urls):
                    try:
                        # Download video
                        temp_video = self._download_video(video_url)
                        if not temp_video:
                            _logger.warning(f"Failed to download video {i+1}, skipping")
                            continue
                        temp_videos.append(temp_video)
                        
                        # Create video clip - use original format from Pexels
                        video_clip = VideoFileClip(temp_video)
                        
                        # Videos from Pexels already come in good mobile formats
                        # No resize needed - avoids PIL.ANTIALIAS compatibility issues
                        
                        # Limit individual video length to max 30 seconds
                        max_individual_length = min(video_duration, 30.0)
                        
                        # Trim to required duration
                        if video_clip.duration > max_individual_length:
                            video_clip = video_clip.subclip(0, max_individual_length)
                        elif video_clip.duration < video_duration:
                            # Loop short videos to fill duration, but don't exceed max length
                            target_duration = min(video_duration, max_individual_length)
                            loops_needed = int(target_duration / video_clip.duration) + 1
                            video_clip = video_clip.loop(duration=target_duration)
                        
                        video_clips.append(video_clip)
                        _logger.info(f"Added video {i+1}/{len(video_urls)}: {temp_video}")
                        
                    except Exception as e:
                        _logger.warning(f"Failed to process video {i+1}: {e}")
                        continue
                
                if not video_clips:
                    return False, "No valid videos could be processed"
                
                # Concatenate all video clips
                final_video = concatenate_videoclips(video_clips, method="compose")
                
                # Add title text overlay for first 3 seconds - PIL method
                if title and title.strip():
                    # Use full title and convert to uppercase
                    title_text = title.upper().strip()
                    
                    try:
                        from PIL import Image, ImageDraw, ImageFont
                        from moviepy.editor import ImageClip
                        import numpy as np
                        
                        # Create a transparent overlay image - auto-adjust to video size
                        # Use smaller dimensions that work with any video format
                        overlay_width = 300  # Universal width for text overlay
                        overlay_height = 150
                        img = Image.new('RGBA', (overlay_width, overlay_height), (0, 0, 0, 0))
                        draw = ImageDraw.Draw(img)
                        
                        # Try to use a system font with better fallback
                        font = None
                        
                        # List of fonts to try in order
                        font_paths = [
                            # Windows fonts
                            "arial.ttf",
                            "Arial.ttf", 
                            "C:/Windows/Fonts/arial.ttf",
                            # Linux DejaVu fonts (installed in Docker)
                            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                            # Ubuntu/Liberation fonts 
                            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                            # Generic Linux fonts
                            "/usr/share/fonts/TTF/arial.ttf",
                            "/System/Library/Fonts/Arial.ttf",  # macOS
                        ]
                        
                        for font_path in font_paths:
                            try:
                                font = ImageFont.truetype(font_path, 26)
                                _logger.info(f"Using font: {font_path}")
                                break
                            except (OSError, IOError):
                                continue
                        
                        # If no TrueType font found, use default
                        if font is None:
                            font = ImageFont.load_default()
                            _logger.warning("No TrueType font found, using default font")
                        
                        # Split text into multiple lines if needed
                        padding = 30  # Fixed padding in pixels
                        max_width = overlay_width - (padding * 2)  # Both sides
                        words = title_text.split()
                        lines = []
                        current_line = ""
                        
                        for word in words:
                            test_line = current_line + (" " if current_line else "") + word
                            bbox = draw.textbbox((0, 0), test_line, font=font)
                            text_width = bbox[2] - bbox[0]
                            if text_width <= max_width:
                                current_line = test_line
                            else:
                                if current_line:
                                    lines.append(current_line)
                                    current_line = word
                                else:
                                    # If single word is too long, add it anyway
                                    lines.append(word)
                                    current_line = ""
                        
                        if current_line:
                            lines.append(current_line)
                        
                        # Calculate text position (centered with padding)
                        line_height = 35
                        total_height = len(lines) * line_height
                        start_y = (overlay_height - total_height) // 2
                        
                        for i, line in enumerate(lines):
                            bbox = draw.textbbox((0, 0), line, font=font)
                            text_width = bbox[2] - bbox[0]
                            x = padding + (max_width - text_width) // 2  # Center within padded area
                            y = start_y + i * line_height
                            
                            # Ensure text doesn't go beyond bounds
                            if x < padding:
                                x = padding
                            if x + text_width > overlay_width - padding:
                                x = overlay_width - padding - text_width
                            
                            # Draw shadow (black, slightly offset)
                            draw.text((x+2, y+2), line, font=font, fill=(0, 0, 0, 200))
                            # Draw main text (white)
                            draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
                        
                        # Convert PIL image to MoviePy ImageClip
                        overlay_array = np.array(img)
                        overlay_clip = ImageClip(overlay_array, duration=3).set_position('center')
                        
                        # Composite over video
                        final_video = CompositeVideoClip([final_video, overlay_clip])
                        _logger.info(f"Added PIL title overlay ({len(lines)} lines): {title_text}")
                        
                    except Exception as e:
                        _logger.warning(f"Failed to add PIL title overlay: {e}")
                        # Final fallback - just log the issue
                        _logger.info(f"Video generated without title: {title_text}")
                
                # Set audio
                final_video = final_video.set_audio(audio_clip)
                
                # Write video optimized for social media (1-2MB target)
                _logger.info(f"Rendering mobile video to {output_path}...")
                final_video.write_videofile(
                    output_path,
                    fps=15,  # Higher FPS for smoother mobile viewing
                    codec='libx264',
                    audio_codec='mp3',
                    preset='fast',  # Good balance of speed/quality
                    bitrate='400k',  # ~1.5MB for 30s video
                    audio_bitrate='64k',
                    remove_temp=True,
                    verbose=False,
                    logger=None,
                    threads=2
                )
                
                # Clean up clips
                for clip in video_clips:
                    try:
                        clip.close()
                    except:
                        pass
                try:
                    final_video.close()
                except:
                    pass
                try:
                    audio_clip.close()
                except:
                    pass
                
                if os.path.exists(output_path):
                    file_size = os.path.getsize(output_path)
                    _logger.info(f"Multi-video generation successful: {output_path} ({file_size} bytes)")
                    return True, None
                else:
                    return False, "Video file was not created"
                    
            finally:
                # Always cleanup temporary videos, even if error occurred
                for temp_video in temp_videos:
                    try:
                        if os.path.exists(temp_video):
                            os.unlink(temp_video)
                            _logger.debug(f"Cleaned up temp video: {temp_video}")
                    except Exception as cleanup_error:
                        _logger.warning(f"Failed to cleanup temp video {temp_video}: {cleanup_error}")
                
        except Exception as e:
            error_msg = f"Multi-video generation error: {str(e)}"
            _logger.exception(error_msg)
            return False, error_msg

    def _download_video(self, url: str) -> Optional[str]:
        """Download video to temporary file"""
        try:
            import requests
            import tempfile
            
            _logger.info(f"Downloading video: {url}")
            response = requests.get(url, timeout=60, stream=True)
            response.raise_for_status()
            
            # Create temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4', prefix='video_')
            temp_path = temp_file.name
            temp_file.close()
            
            # Download with progress
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            _logger.info(f"Downloaded video: {url} -> {temp_path}")
            return temp_path
            
        except Exception as e:
            _logger.warning(f"Failed to download video {url}: {e}")
            return None
    
    def _download_image(self, url: str) -> Optional[str]:
        """Download image to temporary file"""
        try:
            import requests
            
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            # Determine file extension
            content_type = response.headers.get('content-type', '')
            if 'jpeg' in content_type or 'jpg' in content_type:
                ext = '.jpg'
            elif 'png' in content_type:
                ext = '.png'
            else:
                ext = '.jpg'  # Default
            
            # Create temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext, prefix='video_img_')
            temp_file.write(response.content)
            temp_file.close()
            
            _logger.info(f"Downloaded image: {url} -> {temp_file.name}")
            return temp_file.name
            
        except Exception as e:
            _logger.error(f"Failed to download image {url}: {e}")
            return None


def generate_video_for_article(article_id: str, script_text: str, image_url: str, 
                              temp_dir: str = None, output_dir: str = None, 
                              keep_video: bool = False) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Generate video for article with audio from script and image
    
    Args:
        article_id: Article identifier
        script_text: Script text for audio
        image_url: Image URL or path
        temp_dir: Directory for temporary files
        output_dir: Directory for permanent video output (if keep_video=True)
        keep_video: If True, save video permanently in output_dir
        
    Returns:
        Tuple of (success: bool, video_path: Optional[str], error_message: Optional[str])
    """
    try:
        # Import audio generator
        from .audio_generator import generate_audio_for_article, cleanup_temp_audio
        
        if not temp_dir:
            temp_dir = tempfile.gettempdir()
        
        # Step 1: Generate audio
        _logger.info(f"🎵 Generating audio for video {article_id}")
        audio_success, audio_path, audio_error = generate_audio_for_article(article_id, script_text, temp_dir)
        
        if not audio_success:
            return False, None, f"Audio generation failed: {audio_error}"
        
        # Step 2: Determine output path
        if keep_video and output_dir:
            # Ensure output directory exists
            os.makedirs(output_dir, exist_ok=True)
            video_path = os.path.join(output_dir, f"{article_id}_video.mp4")
            _logger.info(f"🎬 Creating permanent video for {article_id} in {output_dir}")
        else:
            video_path = os.path.join(temp_dir, f"{article_id}_video.mp4")
            _logger.info(f"🎬 Creating temporary video for {article_id}")
        
        # Step 3: Generate video
        video_generator = VideoGenerator()
        video_success, video_error = video_generator.generate_video(image_url, audio_path, video_path)
        
        # Step 4: Cleanup audio (video has its own audio track now)
        cleanup_temp_audio(audio_path)
        
        if video_success:
            if keep_video:
                _logger.info(f"📁 Video saved permanently: {video_path}")
            return True, video_path, None
        else:
            return False, None, video_error
            
    except Exception as e:
        error_msg = f"Failed to generate video for article {article_id}: {str(e)}"
        _logger.exception(error_msg)
        return False, None, error_msg


def cleanup_temp_video(video_file_path: str) -> None:
    """Clean up temporary video file"""
    try:
        if video_file_path and os.path.exists(video_file_path):
            os.remove(video_file_path)
            _logger.info(f"Cleaned up temporary video file: {video_file_path}")
    except Exception as e:
        _logger.warning(f"Failed to clean up video file {video_file_path}: {e}")