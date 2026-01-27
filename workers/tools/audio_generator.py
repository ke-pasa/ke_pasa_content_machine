"""
Audio Generator using Azure Speech Services
Converts text scripts to speech for news videos
"""

import os
import logging
from pathlib import Path
from typing import Optional, Tuple
import azure.cognitiveservices.speech as speechsdk

_logger = logging.getLogger('workers.tools.audio_generator')


class AudioGenerator:
    """Generate audio from text using Azure Speech Services"""
    
    def __init__(self):
        self.speech_key = os.getenv('AZURE_SPEECH_KEY')
        self.speech_region = os.getenv('AZURE_SPEECH_REGION')
        
        if not self.speech_key or not self.speech_region:
            raise ValueError("AZURE_SPEECH_KEY and AZURE_SPEECH_REGION must be set in environment variables")
        
        # Configure Azure Speech
        self.speech_config = speechsdk.SpeechConfig(
            subscription=self.speech_key, 
            region=self.speech_region
        )
        
        # Set voice for Russian news (trying male voice again)
        self.speech_config.speech_synthesis_voice_name = "ru-RU-DmitryNeural"
        
        # Set output format (WAV for compatibility)
        self.speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
        )
        
        _logger.info(f"AudioGenerator initialized with voice: {self.speech_config.speech_synthesis_voice_name}")
    
    def generate_audio(self, text: str, output_path: str) -> Tuple[bool, Optional[str]]:
        """
        Generate audio from text and save to file
        
        Args:
            text: Text to convert to speech
            output_path: Full path where to save the audio file
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            if not text or not text.strip():
                return False, "Empty text provided"
            
            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Create audio config for file output
            audio_config = speechsdk.audio.AudioOutputConfig(filename=output_path)
            
            # Create synthesizer
            synthesizer = speechsdk.SpeechSynthesizer(
                speech_config=self.speech_config, 
                audio_config=audio_config
            )
            
            # Add SSML for better pronunciation and pacing for news
            ssml_text = self._wrap_with_ssml(text)
            
            _logger.info(f"Generating audio for text length: {len(text)} characters")
            
            # Synthesize speech
            result = synthesizer.speak_ssml_async(ssml_text).get()
            
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
                _logger.info(f"Audio generation successful. File saved: {output_path} ({file_size} bytes)")
                return True, None
                
            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation_details = result.cancellation_details
                error_msg = f"Speech synthesis canceled: {cancellation_details.reason}"
                if cancellation_details.reason == speechsdk.CancellationReason.Error:
                    error_msg += f" Error details: {cancellation_details.error_details}"
                _logger.error(error_msg)
                return False, error_msg
            else:
                error_msg = f"Speech synthesis failed with reason: {result.reason}"
                _logger.error(error_msg)
                return False, error_msg
                
        except Exception as e:
            error_msg = f"Exception during audio generation: {str(e)}"
            _logger.exception(error_msg)
            return False, error_msg
    
    def _wrap_with_ssml(self, text: str) -> str:
        """
        Wrap text with SSML for better news presentation
        
        Args:
            text: Plain text to wrap
            
        Returns:
            SSML formatted text
        """
        # Clean text and escape XML characters
        clean_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        # Add SSML with optimal news speech rate - moderate speed
        ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="ru-RU">
    <voice name="ru-RU-DmitryNeural">
        <prosody rate="1.25" pitch="medium" volume="medium">
            <break strength="none"/>
            {clean_text}
        </prosody>
    </voice>
</speak>"""
        
        return ssml
    
    def get_audio_duration_estimate(self, text: str) -> float:
        """
        Estimate audio duration in seconds based on text length
        
        Args:
            text: Text to estimate duration for
            
        Returns:
            Estimated duration in seconds
        """
        # Average speaking rate for optimal news: ~160-170 words per minute  
        # Moderate news estimate: 170 words per minute = 2.8 words per second
        words = len(text.split())
        estimated_duration = words / 2.8
        return estimated_duration
    
    def validate_script_length(self, text: str, target_duration: float = 30.0, tolerance: float = 10.0) -> Tuple[bool, str]:
        """
        Validate if script length is appropriate for target duration
        
        Args:
            text: Script text
            target_duration: Target duration in seconds (default 30)
            tolerance: Acceptable deviation in seconds (default 10)
            
        Returns:
            Tuple of (is_valid: bool, message: str)
        """
        estimated_duration = self.get_audio_duration_estimate(text)
        
        if estimated_duration < target_duration - tolerance:
            return False, f"Script too short: {estimated_duration:.1f}s (target: {target_duration}s)"
        elif estimated_duration > target_duration + tolerance:
            return False, f"Script too long: {estimated_duration:.1f}s (target: {target_duration}s)"
        else:
            return True, f"Script length OK: {estimated_duration:.1f}s"


def generate_audio_for_article(article_id: str, script_text: str, temp_dir: str = None) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Convenience function to generate temporary audio for an article
    
    Args:
        article_id: Article identifier
        script_text: Script text to convert
        temp_dir: Directory for temporary audio (default: system temp)
        
    Returns:
        Tuple of (success: bool, temp_audio_file_path: Optional[str], error_message: Optional[str])
    """
    try:
        import tempfile
        
        # Create temporary file for audio
        if not temp_dir:
            temp_dir = tempfile.gettempdir()
        
        temp_audio_path = os.path.join(temp_dir, f"{article_id}_temp.mp3")
        
        generator = AudioGenerator()
        
        # Validate script length
        is_valid, validation_msg = generator.validate_script_length(script_text)
        _logger.info(f"Script validation for {article_id}: {validation_msg}")
        
        # Generate audio
        success, error_msg = generator.generate_audio(script_text, temp_audio_path)
        
        if success:
            return True, temp_audio_path, None
        else:
            return False, None, error_msg
            
    except Exception as e:
        error_msg = f"Failed to generate audio for article {article_id}: {str(e)}"
        _logger.exception(error_msg)
        return False, None, error_msg


def cleanup_temp_audio(audio_file_path: str) -> None:
    """
    Clean up temporary audio file
    
    Args:
        audio_file_path: Path to the temporary audio file
    """
    try:
        if audio_file_path and os.path.exists(audio_file_path):
            os.remove(audio_file_path)
            _logger.info(f"Cleaned up temporary audio file: {audio_file_path}")
    except Exception as e:
        _logger.warning(f"Failed to clean up temporary audio file {audio_file_path}: {e}")