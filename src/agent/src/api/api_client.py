# api/api_client.py
# Cortex IDE API Client Module
# Provides client for communication with logic-practice.com backend

from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


# ============================================================================
# EXCEPTIONS
# ============================================================================

class APIError(Exception):
    """Base exception for API errors."""
    def __init__(self, message: str, code: Optional[str] = None):
        self.message = message
        self.code = code
        super().__init__(message)


class AuthenticationError(APIError):
    """Raised when authentication fails."""
    pass


class SubscriptionError(APIError):
    """Raised when subscription check fails."""
    pass


class LLMError(APIError):
    """Raised when LLM request fails."""
    pass


class UsageError(APIError):
    """Raised when usage tracking fails."""
    pass


class NetworkError(APIError):
    """Raised when network request fails."""
    pass


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class APIConfig:
    """Configuration for API client."""
    base_url: str = "https://api.logic-practice.com"
    api_key: Optional[str] = None
    timeout: int = 30
    max_retries: int = 3
    verify_ssl: bool = True


# ============================================================================
# DATA MODELS
# ============================================================================

class SubscriptionStatus(str, Enum):
    """User subscription status."""
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"
    TRIAL = "trial"


@dataclass
class UserProfile:
    """User profile information."""
    user_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    subscription_status: SubscriptionStatus = SubscriptionStatus.FREE
    created_at: Optional[str] = None


@dataclass
class LLMResponse:
    """Response from LLM API."""
    content: str
    model: str
    usage: Dict[str, int]
    finish_reason: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


# ============================================================================
# API CLIENT
# ============================================================================

class CortexAPIClient:
    """
    Main API client for Cortex IDE.
    Handles authentication, LLM routing, and usage tracking.
    """
    
    _instance: Optional['CortexAPIClient'] = None
    
    def __init__(self, config: Optional[APIConfig] = None):
        self.config = config or APIConfig()
        self._api_key = self.config.api_key
        self._user_profile: Optional[UserProfile] = None
    
    @classmethod
    def get_instance(cls) -> 'CortexAPIClient':
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance."""
        cls._instance = None
    
    def set_api_key(self, api_key: str) -> None:
        """Set the API key for authentication."""
        self._api_key = api_key
    
    async def authenticate(self) -> UserProfile:
        """Authenticate with the API and get user profile."""
        # Stub implementation
        return UserProfile(
            user_id="stub-user",
            email="stub@example.com",
            subscription_status=SubscriptionStatus.FREE
        )
    
    async def get_user_profile(self) -> UserProfile:
        """Get current user profile."""
        if self._user_profile is None:
            self._user_profile = await self.authenticate()
        return self._user_profile
    
    async def call_llm(
        self,
        messages: List[Dict[str, Any]],
        model: str = "claude-3-opus",
        **kwargs
    ) -> LLMResponse:
        """Make an LLM API call."""
        # Stub implementation
        return LLMResponse(
            content="Stub response",
            model=model,
            usage={"input_tokens": 0, "output_tokens": 0}
        )
    
    async def request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Make an API request."""
        # Stub implementation
        return {}
    
    async def get(self, path: str) -> Dict[str, Any]:
        """GET request."""
        return await self.request("GET", path)
    
    async def post(self, path: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """POST request."""
        return await self.request("POST", path, data=data)
    
    async def stream_llm(
        self,
        messages: List[Dict[str, Any]],
        model: str = "claude-3-opus",
        **kwargs
    ):
        """Stream LLM response."""
        # Stub implementation - yield nothing
        yield ""


# Legacy class name alias
APIClient = CortexAPIClient


# ============================================================================
# MODULE-LEVEL FUNCTIONS
# ============================================================================

def get_api_client() -> CortexAPIClient:
    """Get the global API client instance."""
    return CortexAPIClient.get_instance()


def cleanup_api_client() -> None:
    """Cleanup and reset the global API client."""
    CortexAPIClient.reset_instance()


__all__ = [
    # Classes
    "CortexAPIClient",
    "APIClient",
    "APIConfig",
    "UserProfile",
    "SubscriptionStatus",
    "LLMResponse",
    # Exceptions
    "APIError",
    "AuthenticationError",
    "SubscriptionError",
    "LLMError",
    "UsageError",
    "NetworkError",
    # Functions
    "get_api_client",
    "cleanup_api_client",
]
