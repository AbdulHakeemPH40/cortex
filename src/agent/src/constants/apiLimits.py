"""
constants/apiLimits.py
Python conversion of constants/apiLimits.ts (95 lines)

API limits enforced by the Anthropic API — server-side limits that must be
respected client-side to avoid hard API errors.

All values are dependency-free constants (no imports other than stdlib).

Source: api/api/schemas/messages/blocks/ and api/api/config.py
Last verified: 2025-12-22
"""

# =============================================================================
# IMAGE LIMITS
# =============================================================================

# Maximum base64-encoded image size (API enforced, hard limit).
# The API rejects images where the base64 string length exceeds this.
# Note: This is the base64 length, NOT raw bytes.
# Base64 increases size by ~33%.
API_IMAGE_MAX_BASE64_SIZE: int = 5 * 1024 * 1024  # 5 MB

# Target raw image size to stay under base64 limit after encoding.
# Base64 encoding increases size by 4/3, so:
#   raw_size * 4/3 = base64_size  →  raw_size = base64_size * 3/4
IMAGE_TARGET_RAW_SIZE: float = (API_IMAGE_MAX_BASE64_SIZE * 3) / 4  # 3.75 MB

# Client-side maximum dimensions for image resizing.
# The API internally resizes images > 1568px (server-side), but we keep
# client limits at 2000px to preserve quality when beneficial.
# The API_IMAGE_MAX_BASE64_SIZE (5 MB) is the actual hard limit.
IMAGE_MAX_WIDTH: int = 2000
IMAGE_MAX_HEIGHT: int = 2000

# =============================================================================
# PDF LIMITS
# =============================================================================

# Maximum raw PDF file size that fits within the 32 MB API request limit
# after base64 encoding (~33% overhead). 20 MB raw → ~27 MB base64.
PDF_TARGET_RAW_SIZE: int = 20 * 1024 * 1024  # 20 MB

# Maximum number of pages in a PDF accepted by the API.
API_PDF_MAX_PAGES: int = 100

# Size threshold above which PDFs are extracted into page images instead of
# being sent as base64 document blocks. Applies to first-party API only;
# non-first-party always uses extraction.
PDF_EXTRACT_SIZE_THRESHOLD: int = 3 * 1024 * 1024  # 3 MB

# Maximum PDF file size for the page extraction path. PDFs larger than this
# are rejected to avoid processing extremely large files.
PDF_MAX_EXTRACT_SIZE: int = 100 * 1024 * 1024  # 100 MB

# Max pages the Read tool will extract in a single call.
PDF_MAX_PAGES_PER_READ: int = 20

# PDFs with more pages than this get reference treatment on @ mention
# instead of being inlined into context.
PDF_AT_MENTION_INLINE_THRESHOLD: int = 10

# =============================================================================
# MEDIA LIMITS
# =============================================================================

# Maximum number of media items (images + PDFs) allowed per API request.
# The API rejects requests exceeding this with a confusing error.
# We validate client-side to provide a clear message.
API_MAX_MEDIA_PER_REQUEST: int = 100
