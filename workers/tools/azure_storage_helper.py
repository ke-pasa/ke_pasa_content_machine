"""Helper for uploading videos to Azure Storage for Instagram/Facebook sharing.

Videos are uploaded to Azure Blob Storage and made publicly accessible
for Instagram and Facebook video posting requirements.
"""
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from azure.storage.blob import BlobServiceClient, ContentSettings
    AZURE_STORAGE_AVAILABLE = True
except ImportError:
    BlobServiceClient = None
    ContentSettings = None
    AZURE_STORAGE_AVAILABLE = False
    logger.warning("Azure Storage SDK not available. Install with: pip install azure-storage-blob")


class AzureStorageUploader:
    """Helper class for uploading videos to Azure Storage"""
    
    def __init__(self):
        self.account_name = os.getenv('AZURE_STORAGE_ACCOUNT_NAME', 'quepasavideo')
        self.account_key = os.getenv('AZURE_STORAGE_ACCOUNT_KEY')
        self.container_name = os.getenv('AZURE_STORAGE_CONTAINER_NAME', 'video')
        
        if not AZURE_STORAGE_AVAILABLE:
            raise ImportError("Azure Storage SDK not available")
            
        if not self.account_key:
            raise ValueError("AZURE_STORAGE_ACCOUNT_KEY environment variable is required")
            
        # Initialize blob service client
        account_url = f"https://{self.account_name}.blob.core.windows.net"
        self.blob_service_client = BlobServiceClient(
            account_url=account_url, 
            credential=self.account_key
        )
        
    def upload_video(self, video_path: str, custom_filename: Optional[str] = None) -> Optional[str]:
        """
        Upload video to Azure Storage and return public URL.
        
        Args:
            video_path: Local path to video file
            custom_filename: Custom filename (optional, generates unique if not provided)
            
        Returns:
            Public URL of uploaded video, or None on failure
        """
        try:
            if not os.path.exists(video_path):
                logger.error(f"Video file not found: {video_path}")
                return None
                
            # Generate unique filename if not provided
            if custom_filename:
                blob_name = custom_filename
            else:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                unique_id = str(uuid.uuid4())[:8]
                original_name = Path(video_path).stem
                blob_name = f"{timestamp}_{unique_id}_{original_name}.mp4"
                
            logger.info(f"📤 Uploading video to Azure Storage: {blob_name}")
            
            # Get blob client
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, 
                blob=blob_name
            )
            
            # Set content type for video
            content_settings = ContentSettings(content_type='video/mp4')
            
            # Upload file
            with open(video_path, 'rb') as data:
                blob_client.upload_blob(
                    data, 
                    overwrite=True,
                    content_settings=content_settings
                )
                
            # Generate public URL (works when container allows public blob access)
            public_url = f"https://{self.account_name}.blob.core.windows.net/{self.container_name}/{blob_name}"
            
            logger.info(f"✅ Video uploaded successfully: {blob_name}")
            return public_url
            
        except Exception as e:
            logger.error(f"❌ Failed to upload video to Azure Storage: {e}")
            return None
            
    def upload_image(self, image_path: str, custom_filename: Optional[str] = None) -> Optional[str]:
        """
        Upload image to Azure Storage and return public URL.
        
        Args:
            image_path: Local path to image file
            custom_filename: Custom filename (optional, generates unique if not provided)
            
        Returns:
            Public URL of uploaded image, or None on failure
        """
        try:
            if not os.path.exists(image_path):
                logger.error(f"Image file not found: {image_path}")
                return None
                
            # Generate unique filename if not provided
            if custom_filename:
                blob_name = custom_filename
            else:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                unique_id = str(uuid.uuid4())[:8]
                original_name = Path(image_path).name
                blob_name = f"{timestamp}_{unique_id}_{original_name}"
                
            logger.info(f"📤 Uploading image to Azure Storage: {blob_name}")
            
            # Get blob client
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, 
                blob=blob_name
            )
            
            # Detect content type based on file extension
            ext = Path(image_path).suffix.lower()
            content_type_map = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp'
            }
            content_type = content_type_map.get(ext, 'image/jpeg')
            content_settings = ContentSettings(content_type=content_type)
            
            # Upload file
            with open(image_path, 'rb') as data:
                blob_client.upload_blob(
                    data, 
                    overwrite=True,
                    content_settings=content_settings
                )
                
            # Generate public URL
            public_url = f"https://{self.account_name}.blob.core.windows.net/{self.container_name}/{blob_name}"
            
            logger.info(f"✅ Image uploaded successfully: {blob_name}")
            return public_url
            
        except Exception as e:
            logger.error(f"❌ Failed to upload image to Azure Storage: {e}")
            return None
            
    def delete_video(self, blob_name: str) -> bool:
        """
        Delete video from Azure Storage.
        
        Args:
            blob_name: Name of the blob to delete
            
        Returns:
            True if successful, False otherwise
        """
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, 
                blob=blob_name
            )
            blob_client.delete_blob()
            logger.info(f"🗑️ Video deleted from Azure Storage: {blob_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to delete video from Azure Storage: {e}")
            return False
            
    def list_videos(self, prefix: Optional[str] = None) -> list[str]:
        """
        List videos in Azure Storage container.
        
        Args:
            prefix: Filter by blob name prefix (optional)
            
        Returns:
            List of blob names
        """
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            blobs = container_client.list_blobs(name_starts_with=prefix)
            return [blob.name for blob in blobs]
            
        except Exception as e:
            logger.error(f"❌ Failed to list videos from Azure Storage: {e}")
            return []
            
    def cleanup_old_carousels(self, days_old: int = 7) -> int:
        """
        Delete carousel images older than specified days.
        
        Args:
            days_old: Delete files older than this many days (default: 7)
            
        Returns:
            Number of files deleted
        """
        try:
            from datetime import datetime, timedelta, timezone
            
            container_client = self.blob_service_client.get_container_client(self.container_name)
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
            deleted_count = 0
            
            # List all carousel images
            blobs = container_client.list_blobs(name_starts_with='carousel_')
            
            for blob in blobs:
                if blob.last_modified < cutoff_date:
                    try:
                        blob_client = self.blob_service_client.get_blob_client(
                            container=self.container_name,
                            blob=blob.name
                        )
                        blob_client.delete_blob()
                        deleted_count += 1
                        logger.info(f"🗑️ Deleted old carousel: {blob.name}")
                    except Exception as e:
                        logger.error(f"❌ Failed to delete {blob.name}: {e}")
                        
            if deleted_count > 0:
                logger.info(f"✅ Cleaned up {deleted_count} old carousel images")
            return deleted_count
            
        except Exception as e:
            logger.error(f"❌ Failed to cleanup old carousels: {e}")
            return 0


def upload_video_to_azure(video_path: str, custom_filename: Optional[str] = None) -> Optional[str]:
    """
    Convenience function to upload video to Azure Storage.
    
    Args:
        video_path: Local path to video file
        custom_filename: Custom filename (optional)
        
    Returns:
        Public URL of uploaded video, or None on failure
    """
    if not AZURE_STORAGE_AVAILABLE:
        logger.warning("Azure Storage not available, skipping upload")
        return None
        
    try:
        uploader = AzureStorageUploader()
        return uploader.upload_video(video_path, custom_filename)
    except Exception as e:
        logger.error(f"❌ Azure Storage upload failed: {e}")
        return None


def cleanup_local_video(video_path: str) -> bool:
    """
    Clean up local video file after successful Azure upload.
    
    Args:
        video_path: Local path to video file
        
    Returns:
        True if cleaned up successfully
    """
    try:
        if os.path.exists(video_path):
            os.remove(video_path)
            logger.info(f"🧹 Cleaned up local video: {video_path}")
            return True
        return False
    except Exception as e:
        logger.error(f"❌ Failed to cleanup local video: {e}")
        return False