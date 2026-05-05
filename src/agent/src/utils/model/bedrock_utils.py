"""
AWS Bedrock model ID utilities for Cortex AI Agent IDE.

Provides ARN parsing, region prefix extraction, and region routing
for Bedrock-hosted Anthropic models.

NOTE: This file does NOT create AWS clients or handle credentials.
      Your llm_client.py already handles Bedrock provider connections.
      These utilities are purely for model ID parsing and routing logic.
"""

from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Cross-region inference profile prefixes for Bedrock
# ---------------------------------------------------------------------------

BEDROCK_REGION_PREFIXES: Tuple[str, ...] = ('us', 'eu', 'apac', 'global')

# Type alias for region prefix strings
BedrockRegionPrefix = str


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------

def isFoundationModel(modelId: str) -> bool:
    """
    Check if a model ID is a Bedrock foundation model.

    Foundation models start with 'anthropic.' prefix, distinguishing them
    from inference profiles or cross-region routed models.

    Args:
        modelId: Model identifier string

    Returns:
        True if modelId starts with 'anthropic.'

    Example:
        isFoundationModel('anthropic.cortex-sonnet-4-v1:0') → True
        isFoundationModel('us.anthropic.cortex-sonnet-4-v1:0') → False
    """
    return modelId.startswith('anthropic.')


def extractModelIdFromArn(modelId: str) -> str:
    """
    Extract the model/inference profile ID from a Bedrock ARN.

    If the input is not an ARN, returns it unchanged.

    ARN formats supported:
      - arn:aws:bedrock:<region>:<account>:inference-profile/<profile-id>
      - arn:aws:bedrock:<region>:<account>:application-inference-profile/<profile-id>
      - arn:aws:bedrock:<region>::foundation-model/<model-id>

    Args:
        modelId: ARN string or plain model ID

    Returns:
        Model ID extracted from ARN, or original string if not an ARN

    Example:
        extractModelIdFromArn('arn:aws:bedrock:us-east-1:123:inference-profile/us.anthropic.cortex-sonnet-4-v1:0')
        → 'us.anthropic.cortex-sonnet-4-v1:0'

        extractModelIdFromArn('anthropic.cortex-sonnet-4-v1:0')
        → 'anthropic.cortex-sonnet-4-v1:0'
    """
    if not modelId.startswith('arn:'):
        return modelId

    lastSlashIndex = modelId.rfind('/')
    if lastSlashIndex == -1:
        return modelId

    return modelId[lastSlashIndex + 1:]


def getBedrockRegionPrefix(modelId: str) -> Optional[BedrockRegionPrefix]:
    """
    Extract the region prefix from a Bedrock cross-region inference model ID.

    Handles both plain model IDs and full ARN format.

    Region prefixes: 'us', 'eu', 'apac', 'global'

    Args:
        modelId: Model ID or ARN string

    Returns:
        Region prefix string, or None if no prefix found

    Example:
        getBedrockRegionPrefix('eu.anthropic.cortex-sonnet-4-5-20250929-v1:0')
        → 'eu'

        getBedrockRegionPrefix('arn:aws:bedrock:ap-northeast-2:123:inference-profile/global.anthropic.cortex-opus-4-6-v1')
        → 'global'

        getBedrockRegionPrefix('anthropic.cortex-3-5-sonnet-20241022-v2:0')
        → None  (foundation model, no region prefix)

        getBedrockRegionPrefix('claude-sonnet-4-5-20250929')
        → None  (first-party format, not Bedrock)
    """
    # Extract the inference profile ID from ARN format if present
    effectiveModelId = extractModelIdFromArn(modelId)

    for prefix in BEDROCK_REGION_PREFIXES:
        if effectiveModelId.startswith(f'{prefix}.anthropic.'):
            return prefix

    return None


def applyBedrockRegionPrefix(
    modelId: str,
    prefix: BedrockRegionPrefix,
) -> str:
    """
    Apply a region prefix to a Bedrock model ID.

    - If the model already has a different region prefix, it will be replaced
    - If the model is a foundation model (anthropic.*), the prefix will be added
    - If the model is not a Bedrock model, it will be returned as-is

    Args:
        modelId: Model ID or ARN string
        prefix: Region prefix ('us', 'eu', 'apac', 'global')

    Returns:
        Model ID with region prefix applied

    Example:
        applyBedrockRegionPrefix('us.anthropic.cortex-sonnet-4-5-v1:0', 'eu')
        → 'eu.anthropic.cortex-sonnet-4-5-v1:0'

        applyBedrockRegionPrefix('anthropic.cortex-sonnet-4-5-v1:0', 'eu')
        → 'eu.anthropic.cortex-sonnet-4-5-v1:0'

        applyBedrockRegionPrefix('claude-sonnet-4-5-20250929', 'eu')
        → 'claude-sonnet-4-5-20250929'  (not a Bedrock model)
    """
    # Check if it already has a region prefix and replace it
    existingPrefix = getBedrockRegionPrefix(modelId)
    if existingPrefix:
        return modelId.replace(f'{existingPrefix}.', f'{prefix}.', 1)

    # Check if it's a foundation model (anthropic.*) and add the prefix
    if isFoundationModel(modelId):
        return f'{prefix}.{modelId}'

    # Not a Bedrock model format, return as-is
    return modelId


def findFirstMatch(profiles: list[str], substring: str) -> Optional[str]:
    """
    Find the first string in a list that contains a substring.

    Args:
        profiles: List of strings to search
        substring: Substring to match

    Returns:
        First matching string, or None if no match found

    Example:
        findFirstMatch(['eu.anthropic.cortex-sonnet-4', 'us.anthropic.cortex-opus-4'], 'opus')
        → 'us.anthropic.cortex-opus-4'
    """
    for p in profiles:
        if substring in p:
            return p
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    'BEDROCK_REGION_PREFIXES',
    'BedrockRegionPrefix',
    'isFoundationModel',
    'extractModelIdFromArn',
    'getBedrockRegionPrefix',
    'applyBedrockRegionPrefix',
    'findFirstMatch',
]
