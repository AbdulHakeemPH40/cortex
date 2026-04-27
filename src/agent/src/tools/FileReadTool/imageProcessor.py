# imageProcessor.py
# Python conversion of imageProcessor.ts (lines 1-95)
#
# Image processing capabilities for Cortex AI Agent IDE.
# Uses Pillow (PIL) for image manipulation with fallback support.

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple, Union, TYPE_CHECKING

# ============================================================
# TYPE DEFINITIONS
# ============================================================

@dataclass
class ImageMetadata:
    """Image metadata returned from processing."""
    width: int
    height: int
    format: str


@dataclass
class ResizeOptions:
    """Options for image resizing."""
    fit: str = "inside"  # 'inside', 'outside', 'cover', 'contain', 'fill'
    without_enlargement: bool = True


@dataclass
class JpegOptions:
    """Options for JPEG encoding."""
    quality: int = 85


@dataclass
class PngOptions:
    """Options for PNG encoding."""
    compression_level: int = 6
    palette: bool = False
    colors: int = 256


@dataclass
class WebpOptions:
    """Options for WebP encoding."""
    quality: int = 85


# SharpInstance equivalent - callable that processes images
SharpInstance = Any  # PIL.Image.Image after processing
SharpFunction = Callable[[bytes], SharpInstance]

# Creator options for generating new images
@dataclass
class SharpCreatorOptions:
    """Options for creating new images from scratch."""
    width: int
    height: int
    channels: int  # 3 for RGB, 4 for RGBA
    background: Tuple[int, int, int]  # RGB color tuple


# Type alias for creator function - can accept options or dict
SharpCreator = Callable[..., SharpInstance]  # Accepts SharpCreatorOptions or dict


# ============================================================
# IMAGE PROCESSOR MODULE CACHE
# ============================================================

_image_processor_module: Optional[SharpFunction] = None
_image_creator_module: Optional[SharpCreator] = None


def _is_in_bundled_mode() -> bool:
    """Check if running in bundled mode."""
    import os
    # Check for environment variable or bundled mode indicator
    return os.environ.get('CLAUDE_CODE_BUNDLED', '').lower() in ('1', 'true', 'yes')


# ============================================================
# IMAGE PROCESSOR
# ============================================================

async def get_image_processor() -> SharpFunction:
    """
    Get the image processor function.
    
    Tries native image processor first in bundled mode,
    falls back to Pillow (PIL) otherwise.
    
    Returns:
        Callable that takes bytes and returns a PIL Image for processing
    """
    global _image_processor_module
    
    if _image_processor_module is not None:
        return _image_processor_module
    
    if _is_in_bundled_mode():
        # Try to load native image processor first
        try:
            # Would use image-processor-napi in bundled mode
            # For now, skip to Pillow fallback
            pass
        except ImportError:
            # Fall back to Pillow
            pass
    
    # Use Pillow (PIL) as the primary image processor in Python
    try:
        from PIL import Image
        _image_processor_module = _create_pil_processor(Image)
        return _image_processor_module
    except ImportError:
        raise ImportError(
            "Pillow (PIL) is required for image processing. "
            "Install with: pip install Pillow"
        )


def _create_pil_processor(Image) -> SharpFunction:
    """Create a Sharp-like interface using PIL."""
    
    class PILImageWrapper:
        """Wrapper that provides Sharp-like interface for PIL Image."""
        
        def __init__(self, image: Image.Image):
            self._image = image
            self._format = image.format or 'PNG'
            self._quality = 85
            self._compression_level = 6
        
        def metadata(self) -> ImageMetadata:
            """Get image metadata."""
            return ImageMetadata(
                width=self._image.width,
                height=self._image.height,
                format=self._format.lower()
            )
        
        def resize(
            self,
            width: int,
            height: int,
            options: Optional[Union[ResizeOptions, Dict[str, Any]]] = None,
        ) -> 'PILImageWrapper':
            """Resize the image."""
            # Parse options
            fit = 'inside'
            without_enlargement = True
            
            if options:
                if isinstance(options, dict):
                    fit = options.get('fit', 'inside')
                    without_enlargement = options.get('withoutEnlargement', True)
                else:
                    fit = options.fit
                    without_enlargement = options.without_enlargement
            
            # Store original size for without_enlargement check
            orig_width, orig_height = self._image.size
            
            # Map Sharp fit modes to PIL resize behavior
            if fit == 'inside':
                # Fit within bounds, maintain aspect ratio
                if without_enlargement and (width > orig_width or height > orig_height):
                    # Don't enlarge - just keep original size
                    pass
                else:
                    self._image.thumbnail((width, height), Image.Resampling.LANCZOS)
            elif fit == 'outside':
                # Fill bounds, may exceed on one dimension
                self._image.thumbnail(
                    (width * 2, height * 2),  # Overshoot then crop
                    Image.Resampling.LANCZOS
                )
            elif fit == 'cover':
                # Cover the area, crop excess (sharp 'cover' = exact dimensions)
                self._image = self._image.resize(
                    (width, height),
                    Image.Resampling.LANCZOS
                )
            elif fit == 'contain':
                # Same as 'inside' - fit within bounds
                self._image.thumbnail((width, height), Image.Resampling.LANCZOS)
            else:
                # Default resize - exact dimensions
                self._image = self._image.resize(
                    (width, height),
                    Image.Resampling.LANCZOS
                )
            
            return self
        
        def jpeg(self, options: Optional[Union[JpegOptions, Dict[str, Any]]] = None) -> 'PILImageWrapper':
            """Set JPEG format with options."""
            self._format = 'JPEG'
            if options:
                if isinstance(options, dict):
                    self._quality = options.get('quality', 85)
                else:
                    self._quality = options.quality
            return self
        
        def png(self, options: Optional[Union[PngOptions, Dict[str, Any]]] = None) -> 'PILImageWrapper':
            """Set PNG format with options."""
            self._format = 'PNG'
            if options:
                if isinstance(options, dict):
                    self._compression_level = options.get('compressionLevel', 6)
                else:
                    self._compression_level = options.compression_level
            return self
        
        def webp(self, options: Optional[Union[WebpOptions, Dict[str, Any]]] = None) -> 'PILImageWrapper':
            """Set WebP format with options."""
            self._format = 'WEBP'
            if options:
                if isinstance(options, dict):
                    self._quality = options.get('quality', 85)
                else:
                    self._quality = options.quality
            return self
        
        def to_buffer(self) -> bytes:
            """Convert image to bytes buffer."""
            buffer = io.BytesIO()
            
            # Handle format-specific save options
            save_kwargs = {}
            
            if self._format.upper() == 'JPEG':
                save_kwargs['quality'] = self._quality
                # Convert RGBA to RGB for JPEG
                if self._image.mode == 'RGBA':
                    background = Image.new('RGB', self._image.size, (255, 255, 255))
                    background.paste(self._image, mask=self._image.split()[3])
                    self._image = background
            elif self._format.upper() == 'PNG':
                save_kwargs['compress_level'] = self._compression_level
            elif self._format.upper() == 'WEBP':
                save_kwargs['quality'] = self._quality
            
            self._image.save(buffer, format=self._format, **save_kwargs)
            return buffer.getvalue()
        
        # Alias for TypeScript compatibility
        toBuffer = to_buffer
    
    def processor(input_buffer: bytes) -> PILImageWrapper:
        """Process an image buffer and return a Sharp-like wrapper."""
        image = Image.open(io.BytesIO(input_buffer))
        return PILImageWrapper(image)
    
    return processor


# ============================================================
# IMAGE CREATOR
# ============================================================

async def get_image_creator() -> SharpCreator:
    """
    Get the image creator function for generating new images from scratch.
    
    Note: Always uses PIL directly for image creation.
    
    Returns:
        Callable that creates new images from scratch
    """
    global _image_creator_module
    
    if _image_creator_module is not None:
        return _image_creator_module
    
    try:
        from PIL import Image
        _image_creator_module = _create_pil_creator(Image)
        return _image_creator_module
    except ImportError:
        raise ImportError(
            "Pillow (PIL) is required for image creation. "
            "Install with: pip install Pillow"
        )


def _create_pil_creator(Image) -> SharpCreator:
    """Create a Sharp-like creator using PIL."""
    
    class PILCreatorWrapper:
        """Wrapper for PIL image creation with Sharp-like interface."""
        
        def __init__(self, image: Image.Image):
            self._image = image
            self._format = 'PNG'
            self._quality = 85
        
        def metadata(self) -> ImageMetadata:
            """Get image metadata."""
            return ImageMetadata(
                width=self._image.width,
                height=self._image.height,
                format=self._format.lower()
            )
        
        def resize(self, width: int, height: int, options=None) -> 'PILCreatorWrapper':
            """Resize the image."""
            self._image = self._image.resize(
                (width, height),
                Image.Resampling.LANCZOS
            )
            return self
        
        def jpeg(self, options=None) -> 'PILCreatorWrapper':
            """Set JPEG format."""
            self._format = 'JPEG'
            if options and hasattr(options, 'quality'):
                self._quality = options.quality
            return self
        
        def png(self, options=None) -> 'PILCreatorWrapper':
            """Set PNG format."""
            self._format = 'PNG'
            return self
        
        def webp(self, options=None) -> 'PILCreatorWrapper':
            """Set WebP format."""
            self._format = 'WEBP'
            if options and hasattr(options, 'quality'):
                self._quality = options.quality
            return self
        
        def to_buffer(self) -> bytes:
            """Convert to bytes."""
            buffer = io.BytesIO()
            self._image.save(buffer, format=self._format, quality=self._quality)
            return buffer.getvalue()
        
        toBuffer = to_buffer
    
    def creator(options: Union[SharpCreatorOptions, Dict[str, Any]]) -> PILCreatorWrapper:
        """Create a new image from scratch."""
        if isinstance(options, dict):
            width = options.get('width', 100)
            height = options.get('height', 100)
            channels = options.get('channels', 3)
            background = options.get('background', (255, 255, 255))
        else:
            width = options.width
            height = options.height
            channels = options.channels
            background = options.background
        
        # Determine mode based on channels
        mode = 'RGB' if channels == 3 else 'RGBA'
        
        # Create image with background color
        if mode == 'RGBA':
            color = (*background, 255)  # Add alpha
        else:
            color = background
        
        image = Image.new(mode, (width, height), color)
        return PILCreatorWrapper(image)
    
    return creator


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

async def process_image(
    image_buffer: bytes,
    resize: Optional[Tuple[int, int]] = None,
    format: str = 'jpeg',
    quality: int = 85,
) -> bytes:
    """
    Process an image with common operations.
    
    Args:
        image_buffer: Input image bytes
        resize: Optional (width, height) tuple to resize
        format: Output format ('jpeg', 'png', 'webp')
        quality: Quality for lossy formats
    
    Returns:
        Processed image bytes
    """
    processor = await get_image_processor()
    img = processor(image_buffer)
    
    if resize:
        width, height = resize
        img.resize(width, height, ResizeOptions(fit='inside'))
    
    format_lower = format.lower()
    if format_lower == 'jpeg':
        img.jpeg(JpegOptions(quality=quality))
    elif format_lower == 'png':
        img.png()
    elif format_lower == 'webp':
        img.webp(WebpOptions(quality=quality))
    
    return img.to_buffer()


async def create_image(
    width: int,
    height: int,
    background: Tuple[int, int, int] = (255, 255, 255),
    format: str = 'png',
) -> bytes:
    """
    Create a new solid-color image.
    
    Args:
        width: Image width
        height: Image height
        background: RGB color tuple
        format: Output format
    
    Returns:
        Image bytes
    """
    creator = await get_image_creator()
    options = SharpCreatorOptions(
        width=width,
        height=height,
        channels=3,
        background=background,
    )
    img = creator(options)
    
    format_lower = format.lower()
    if format_lower == 'jpeg':
        img.jpeg()
    elif format_lower == 'webp':
        img.webp()
    
    return img.to_buffer()


async def get_image_metadata(image_buffer: bytes) -> ImageMetadata:
    """
    Get metadata for an image.
    
    Args:
        image_buffer: Image bytes
    
    Returns:
        ImageMetadata with width, height, and format
    """
    processor = await get_image_processor()
    img = processor(image_buffer)
    return img.metadata()


# ============================================================
# SYNC VERSIONS FOR NON-ASYNC CONTEXTS
# ============================================================

def get_image_processor_sync() -> SharpFunction:
    """Synchronous version of get_image_processor."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(get_image_processor())


def get_image_creator_sync() -> SharpCreator:
    """Synchronous version of get_image_creator."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(get_image_creator())


# ============================================================
# PUBLIC API EXPORTS
# ============================================================

__all__ = [
    # Types
    'ImageMetadata',
    'ResizeOptions',
    'JpegOptions',
    'PngOptions',
    'WebpOptions',
    'SharpCreatorOptions',
    
    # Type aliases
    'SharpInstance',
    'SharpFunction',
    'SharpCreator',
    
    # Main functions
    'get_image_processor',
    'get_image_creator',
    
    # Convenience functions
    'process_image',
    'create_image',
    'get_image_metadata',
    
    # Sync versions
    'get_image_processor_sync',
    'get_image_creator_sync',
]
