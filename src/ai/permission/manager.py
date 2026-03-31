"""
Permission Manager for Cortex AI Agent
Manages permissions, grants, and safety checks
"""

import re
import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path

from src.ai.permission.types import (
    PermissionType, PermissionScope, PermissionStatus,
    PermissionRequest, PermissionGrant, PermissionCheckResult,
    PermissionCardData, CommandAnalysis, CommandSafety,
    PERMISSION_CARD_CONFIGS, DANGEROUS_PATTERNS, WARNING_PATTERNS,
    SAFE_COMMANDS
)
from src.utils.logger import get_logger

log = get_logger("permission_manager")


class PermissionManager:
    """
    Manages user permissions for tool execution.
    Handles permission checks, grants, and persistence.
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        self._grants: Dict[str, List[PermissionGrant]] = {}  # session_id -> grants
        self._requests: Dict[str, PermissionRequest] = {}  # request_id -> request
        self._storage_path = storage_path or self._get_default_storage_path()
        self._load_grants()
        log.info("PermissionManager initialized")
    
    def _get_default_storage_path(self) -> str:
        """Get default storage path for permissions."""
        home = Path.home()
        cortex_dir = home / ".cortex"
        cortex_dir.mkdir(exist_ok=True)
        return str(cortex_dir / "permissions.json")
    
    def _load_grants(self):
        """Load persisted grants from disk."""
        if os.path.exists(self._storage_path):
            try:
                with open(self._storage_path, 'r') as f:
                    data = json.load(f)
                
                for session_id, grants_data in data.items():
                    self._grants[session_id] = []
                    for grant_data in grants_data:
                        grant = PermissionGrant(
                            tool=grant_data['tool'],
                            permission_type=PermissionType(grant_data['permission_type']),
                            access=grant_data['access'],
                            scope=PermissionScope(grant_data['scope']),
                            session_id=grant_data['session_id'],
                            granted_at=datetime.fromisoformat(grant_data['granted_at']),
                            expires=datetime.fromisoformat(grant_data['expires']) if grant_data.get('expires') else None,
                        )
                        self._grants[session_id].append(grant)
                
                log.info("Loaded %d permission grants", sum(len(g) for g in self._grants.values()))
            except Exception as e:
                log.error("Failed to load permissions: %s", e)
    
    def _save_grants(self):
        """Save grants to disk."""
        try:
            data = {}
            for session_id, grants in self._grants.items():
                data[session_id] = [grant.to_dict() for grant in grants]
            
            with open(self._storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.error("Failed to save permissions: %s", e)
    
    def check_permission(
        self,
        session_id: str,
        tool: str,
        permission_type: PermissionType,
        requested_access: List[str]
    ) -> PermissionCheckResult:
        """
        Check if permission is granted for a tool.
        
        Returns:
            PermissionCheckResult with grant status
        """
        # Get grants for this session
        grants = self._grants.get(session_id, [])
        
        # Also check for global scope grants from any session (for "Always remember" functionality)
        if not grants:
            for sid, session_grants in self._grants.items():
                for grant in session_grants:
                    if (grant.scope == PermissionScope.GLOBAL and 
                        grant.tool == tool and 
                        grant.permission_type == permission_type and
                        grant.is_valid()):
                        grants.append(grant)
        
        # Find matching grant
        for grant in grants:
            if (grant.tool == tool and 
                grant.permission_type == permission_type and
                grant.is_valid()):
                
                # Check if access level is sufficient
                has_access = all(
                    access in grant.access or 'unrestricted' in grant.access
                    for access in requested_access
                )
                
                if has_access:
                    return PermissionCheckResult(
                        granted=True,
                        permission=grant
                    )
                else:
                    # Permission exists but insufficient scope
                    return PermissionCheckResult(
                        granted=False,
                        reason="insufficient_scope",
                        required_access=requested_access,
                        existing_access=grant.access
                    )
        
        # No existing permission
        return PermissionCheckResult(
            granted=False,
            reason="no_permission",
            required_access=requested_access
        )
    
    def request_permission(
        self,
        session_id: str,
        tool: str,
        permission_type: PermissionType,
        requested_access: List[str],
        metadata: Optional[Dict[str, Any]] = None
    ) -> PermissionRequest:
        """
        Create a new permission request.
        
        Returns:
            PermissionRequest object
        """
        import uuid
        
        request = PermissionRequest(
            id=str(uuid.uuid4()),
            tool=tool,
            permission_type=permission_type,
            requested_access=requested_access,
            session_id=session_id,
            metadata=metadata or {}
        )
        
        self._requests[request.id] = request
        
        log.info(
            "Created permission request: %s for %s (%s)",
            request.id, tool, permission_type.value
        )
        
        return request
    
    def grant_permission(
        self,
        request_id: str,
        scope: PermissionScope = PermissionScope.SESSION,
        duration_hours: Optional[int] = None
    ) -> Optional[PermissionGrant]:
        """
        Grant a permission request.
        
        Args:
            request_id: ID of the permission request
            scope: Scope of the grant (session/workspace/global)
            duration_hours: Hours until expiration (None for no expiration)
            
        Returns:
            PermissionGrant object or None if request not found
        """
        request = self._requests.get(request_id)
        if not request or request.status != PermissionStatus.PENDING:
            log.warning("Permission request not found or not pending: %s", request_id)
            return None
        
        # Calculate expiration
        expires = None
        if duration_hours:
            expires = datetime.now() + timedelta(hours=duration_hours)
        elif scope == PermissionScope.SESSION:
            expires = datetime.now() + timedelta(hours=1)  # 1 hour default
        
        # Create grant
        grant = PermissionGrant(
            tool=request.tool,
            permission_type=request.permission_type,
            access=request.requested_access,
            scope=scope,
            session_id=request.session_id,
            expires=expires,
            request_id=request_id,
            metadata=request.metadata
        )
        
        # Store grant
        if request.session_id not in self._grants:
            self._grants[request.session_id] = []
        self._grants[request.session_id].append(grant)
        
        # Update request status
        request.status = PermissionStatus.GRANTED
        
        # Persist if workspace or global scope
        if scope in [PermissionScope.WORKSPACE, PermissionScope.GLOBAL]:
            self._save_grants()
        
        log.info(
            "Granted permission: %s (%s scope, expires: %s)",
            request.tool, scope.value, expires
        )
        
        return grant
    
    def deny_permission(self, request_id: str, reason: str = ""):
        """Deny a permission request."""
        request = self._requests.get(request_id)
        if request:
            request.status = PermissionStatus.DENIED
            request.reason = reason
            log.info("Denied permission request: %s (%s)", request_id, reason)
    
    def create_permission_card(
        self,
        request: PermissionRequest
    ) -> PermissionCardData:
        """
        Create permission card data for UI display.
        
        Returns:
            PermissionCardData with UI information
        """
        config = PERMISSION_CARD_CONFIGS.get(
            request.permission_type,
            {
                "title": "Permission Requested",
                "description": f"This tool ({request.tool}) wants access",
                "risks": ["Unknown risks"],
                "safeguards": ["Review carefully"],
            }
        )
        
        return PermissionCardData(
            request_id=request.id,
            tool=request.tool,
            permission_type=request.permission_type,
            requested_access=request.requested_access,
            title=config["title"],
            description=config["description"],
            risks=config["risks"],
            safeguards=config["safeguards"],
        )
    
    def analyze_command(self, command: str) -> CommandAnalysis:
        """
        Analyze a command for safety.
        
        Returns:
            CommandAnalysis with safety assessment
        """
        patterns_detected = []
        
        # Check dangerous patterns
        for pattern, description in DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                patterns_detected.append(f"DANGEROUS: {description}")
        
        if patterns_detected:
            return CommandAnalysis(
                command=command,
                safety=CommandSafety.DANGEROUS,
                patterns_detected=patterns_detected,
                requires_confirmation=True,
                explanation="This command contains dangerous operations that could harm your system."
            )
        
        # Check warning patterns
        for pattern, description in WARNING_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                patterns_detected.append(f"WARNING: {description}")
        
        if patterns_detected:
            return CommandAnalysis(
                command=command,
                safety=CommandSafety.WARNING,
                patterns_detected=patterns_detected,
                requires_confirmation=True,
                explanation="This command may modify files or system state."
            )
        
        # Check if command is in safe list
        command_base = command.strip().split()[0] if command else ""
        if command_base in SAFE_COMMANDS:
            return CommandAnalysis(
                command=command,
                safety=CommandSafety.SAFE,
                patterns_detected=[],
                requires_confirmation=False,
                explanation="This is a commonly used safe command."
            )
        
        # Unknown command - treat as warning
        return CommandAnalysis(
            command=command,
            safety=CommandSafety.WARNING,
            patterns_detected=["Unknown command"],
            requires_confirmation=True,
            explanation="This command is not in the safe command list."
        )
    
    def revoke_permission(
        self,
        session_id: str,
        tool: str,
        permission_type: PermissionType
    ):
        """Revoke a specific permission."""
        if session_id in self._grants:
            self._grants[session_id] = [
                g for g in self._grants[session_id]
                if not (g.tool == tool and g.permission_type == permission_type)
            ]
            self._save_grants()
            log.info("Revoked permission: %s (%s)", tool, permission_type.value)
    
    def get_grants(self, session_id: str) -> List[PermissionGrant]:
        """Get all grants for a session."""
        return [g for g in self._grants.get(session_id, []) if g.is_valid()]
    
    def clear_session(self, session_id: str):
        """Clear all grants for a session."""
        if session_id in self._grants:
            del self._grants[session_id]
            self._save_grants()
            log.info("Cleared permissions for session: %s", session_id)


# Singleton instance
_permission_manager = None


def get_permission_manager() -> PermissionManager:
    """Get singleton instance of PermissionManager."""
    global _permission_manager
    if _permission_manager is None:
        _permission_manager = PermissionManager()
    return _permission_manager
