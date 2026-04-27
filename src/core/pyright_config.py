"""Pyright configuration management for Cortex IDE.

Supports pyrightconfig.json and pyproject.toml with comprehensive
configuration options for type checking, diagnostics, and execution.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from enum import Enum
from src.utils.logger import get_logger

log = get_logger("pyright_config")


class TypeCheckingMode(Enum):
    """Pyright type checking modes."""
    OFF = "off"
    BASIC = "basic"
    STANDARD = "standard"
    STRICT = "strict"


@dataclass
class PyrightConfig:
    """Complete Pyright configuration with all supported options.
    
    See: https://github.com/microsoft/pyright/blob/main/docs/configuration.md
    """
    
    # Environment Settings
    pythonVersion: Optional[str] = None
    pythonPlatform: Optional[str] = None
    
    # Type Checking Mode
    typeCheckingMode: TypeCheckingMode = TypeCheckingMode.BASIC
    
    # Include/Exclude Settings
    include: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=lambda: [
        "**/__pycache__",
        "**/node_modules",
        "**/.git",
        "**/venv",
        "**/env",
        ".venv",
        ".env"
    ])
    ignore: List[str] = field(default_factory=list)
    
    # Execution Environment
    extraPaths: List[str] = field(default_factory=list)
    venv: Optional[str] = None
    venvPath: Optional[str] = None
    
    # Type Evaluation Settings
    strictListInference: bool = False
    strictDictionaryInference: bool = False
    strictSetInference: bool = False
    analyzeUnannotatedFunctions: bool = True
    strictParameterNoneValue: bool = True
    enableTypeIgnoreComments: bool = True
    deprecateTypingAliases: bool = False
    enableReachabilityAnalysis: bool = False
    enableExperimentalFeatures: bool = False
    disableBytesTypePromotions: bool = True
    
    # Report Settings - Diagnostic Severity Overrides
    # Options: "error", "warning", "information", "none"
    reportGeneralTypeIssues: Optional[str] = None
    reportPropertyTypeMismatch: Optional[str] = None
    reportFunctionMemberAccess: Optional[str] = None
    reportMissingImports: Optional[str] = "error"
    reportMissingTypeStubs: Optional[str] = "warning"
    reportImportCycles: Optional[str] = None
    reportUnusedImport: Optional[str] = "warning"
    reportUnusedClass: Optional[str] = None
    reportUnusedFunction: Optional[str] = None
    reportUnusedVariable: Optional[str] = "warning"
    reportDuplicateImport: Optional[str] = "warning"
    reportWildcardImportFromLibrary: Optional[str] = "warning"
    reportAbstractUsage: Optional[str] = None
    reportArgumentType: Optional[str] = None
    reportAssertTypes: Optional[str] = None
    reportAssignmentType: Optional[str] = None
    reportAttributeAccessIssue: Optional[str] = None
    reportCallIssue: Optional[str] = None
    reportInconsistentOverload: Optional[str] = None
    reportIndexIssue: Optional[str] = None
    reportInvalidTypeForm: Optional[str] = None
    reportMissingModuleSource: Optional[str] = None
    reportMissingParameterType: Optional[str] = None
    reportMissingReturnType: Optional[str] = None
    reportMissingTypeArgument: Optional[str] = None
    reportOptionalCall: Optional[str] = None
    reportOptionalIterable: Optional[str] = None
    reportOptionalMemberAccess: Optional[str] = None
    reportOptionalOperand: Optional[str] = None
    reportOptionalSubscript: Optional[str] = None
    reportPossiblyUnboundVariable: Optional[str] = None
    reportRedeclaration: Optional[str] = None
    reportReturnType: Optional[str] = None
    reportSelfClsParameterName: Optional[str] = None
    reportTypeCommentUsage: Optional[str] = None
    reportUnknownArgumentType: Optional[str] = None
    reportUnknownLambdaType: Optional[str] = None
    reportUnknownMemberType: Optional[str] = None
    reportUnknownParameterType: Optional[str] = None
    reportUnknownVariableType: Optional[str] = None
    reportUnnecessaryCast: Optional[str] = None
    reportUnnecessaryComparison: Optional[str] = None
    reportUnnecessaryContains: Optional[str] = None
    reportUnnecessaryIsInstance: Optional[str] = None
    reportUntypedBaseClass: Optional[str] = None
    reportUntypedClassDecorator: Optional[str] = None
    reportUntypedFunctionDecorator: Optional[str] = None
    reportUntypedNamedTuple: Optional[str] = None
    
    # Customizable severity overrides (for pyrightconfig.json compatibility)
    diagnosticSeverityOverrides: Dict[str, str] = field(default_factory=dict)
    
    @classmethod
    def from_file(cls, config_path: str) -> "PyrightConfig":
        """Load configuration from pyrightconfig.json or pyproject.toml.
        
        Priority: pyrightconfig.json > pyproject.toml
        """
        path = Path(config_path)
        
        if not path.exists():
            log.warning(f"Config file not found: {config_path}")
            return cls()  # Return defaults
        
        try:
            if path.name == "pyrightconfig.json":
                return cls._from_pyrightconfig(path)
            elif path.name == "pyproject.toml":
                return cls._from_pyproject(path)
            else:
                # Try as pyrightconfig.json
                return cls._from_pyrightconfig(path)
        except Exception as e:
            log.error(f"Failed to load config from {config_path}: {e}")
            return cls()
    
    @classmethod
    def _from_pyrightconfig(cls, path: Path) -> "PyrightConfig":
        """Load from pyrightconfig.json."""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Convert typeCheckingMode string to enum
        if "typeCheckingMode" in data:
            data["typeCheckingMode"] = TypeCheckingMode(data["typeCheckingMode"])
        
        return cls(**data)
    
    @classmethod
    def _from_pyproject(cls, path: Path) -> "PyrightConfig":
        """Load from pyproject.toml [tool.pyright] section."""
        try:
            import tomllib
        except ImportError:
            # Python < 3.11
            try:
                import tomli as tomllib
            except ImportError:
                log.error("tomli package required for pyproject.toml support")
                return cls()
        
        with open(path, 'rb') as f:
            data = tomllib.load(f)
        
        pyright_data = data.get("tool", {}).get("pyright", {})
        
        # Convert typeCheckingMode string to enum
        if "typeCheckingMode" in pyright_data:
            pyright_data["typeCheckingMode"] = TypeCheckingMode(pyright_data["typeCheckingMode"])
        
        return cls(**pyright_data)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {}
        for key, value in asdict(self).items():
            if value is not None:
                if isinstance(value, Enum):
                    result[key] = value.value
                elif isinstance(value, (list, dict)) and len(value) == 0:
                    continue  # Skip empty collections
                elif isinstance(value, dict):
                    result[key] = value
                elif isinstance(value, list):
                    result[key] = value
                elif not isinstance(value, (list, dict)):
                    result[key] = value
        return result
    
    def save(self, path: str):
        """Save configuration to pyrightconfig.json."""
        config_path = Path(path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2)
        
        log.info(f"Pyright configuration saved to {path}")
    
    def get_effective_severity(self, diagnostic_code: str) -> str:
        """Get effective severity for a diagnostic code."""
        # Check explicit overrides first
        if diagnostic_code in self.diagnosticSeverityOverrides:
            return self.diagnosticSeverityOverrides[diagnostic_code]
        
        # Check report* settings
        report_setting = getattr(self, f"report{diagnostic_code}", None)
        if report_setting:
            return report_setting
        
        # Default based on type checking mode
        severity_map = {
            TypeCheckingMode.OFF: "none",
            TypeCheckingMode.BASIC: "warning",
            TypeCheckingMode.STANDARD: "error",
            TypeCheckingMode.STRICT: "error"
        }
        return severity_map.get(self.typeCheckingMode, "warning")


class PyrightConfigManager:
    """Manages Pyright configuration with auto-discovery and IDE settings sync."""
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.config: PyrightConfig = PyrightConfig()
        self._config_path: Optional[Path] = None
        self._load_config()
    
    def _load_config(self):
        """Auto-discover and load configuration from project."""
        # Priority: pyrightconfig.json > pyproject.toml > defaults
        
        pyright_json = self.project_root / "pyrightconfig.json"
        if pyright_json.exists():
            log.info(f"Loading Pyright config from {pyright_json}")
            self.config = PyrightConfig.from_file(str(pyright_json))
            self._config_path = pyright_json
            return
        
        pyproject_toml = self.project_root / "pyproject.toml"
        if pyproject_toml.exists():
            try:
                log.info(f"Loading Pyright config from {pyproject_toml}")
                self.config = PyrightConfig.from_file(str(pyproject_toml))
                self._config_path = pyproject_toml
                return
            except Exception as e:
                log.warning(f"Failed to load pyproject.toml: {e}")
        
        log.info("Using default Pyright configuration")
        self.config = PyrightConfig()
        self._config_path = None
    
    def get_config_for_server(self) -> Dict[str, Any]:
        """Get configuration formatted for LSP server initialization."""
        return {
            "python": {
                "pythonVersion": self.config.pythonVersion,
                "pythonPlatform": self.config.pythonPlatform,
            },
            "analysis": {
                "typeCheckingMode": self.config.typeCheckingMode.value,
                "diagnosticSeverityOverrides": self.config.diagnosticSeverityOverrides,
                "strictListInference": self.config.strictListInference,
                "strictDictionaryInference": self.config.strictDictionaryInference,
                "strictSetInference": self.config.strictSetInference,
                "analyzeUnannotatedFunctions": self.config.analyzeUnannotatedFunctions,
            }
        }
    
    def update_setting(self, key: str, value: Any):
        """Update a configuration setting."""
        if hasattr(self.config, key):
            setattr(self.config, key, value)
            log.info(f"Updated Pyright setting: {key} = {value}")
        else:
            log.warning(f"Unknown Pyright setting: {key}")
    
    def save_config(self, path: Optional[str] = None):
        """Save current configuration to pyrightconfig.json.
        
        Args:
            path: Optional custom path. If not provided, saves to project root.
        """
        if path:
            save_path = Path(path)
        elif self._config_path and self._config_path.name == "pyrightconfig.json":
            save_path = self._config_path
        else:
            save_path = self.project_root / "pyrightconfig.json"
        
        self.config.save(str(save_path))
        self._config_path = save_path
    
    def create_default_config(self, type_checking_mode: str = "basic"):
        """Create a sensible default configuration file."""
        self.config = PyrightConfig(
            typeCheckingMode=TypeCheckingMode(type_checking_mode),
            include=["src", "lib"],
            exclude=[
                "**/__pycache__",
                "**/node_modules",
                "**/.git",
                "**/venv",
                "**/env",
                "**/tests",
                "**/test"
            ],
            reportMissingImports="error",
            reportMissingTypeStubs="warning",
            reportUnusedImport="warning",
            reportUnusedVariable="warning",
            reportDuplicateImport="warning",
        )
        self.save_config()
        log.info(f"Created default Pyright config with mode: {type_checking_mode}")
    
    def get_type_checking_modes(self) -> List[Dict[str, str]]:
        """Get available type checking modes with descriptions."""
        return [
            {"value": "off", "label": "Off", "description": "No type checking"},
            {"value": "basic", "label": "Basic", "description": "Basic type checking (recommended)"},
            {"value": "standard", "label": "Standard", "description": "Standard type checking"},
            {"value": "strict", "label": "Strict", "description": "Strict type checking (maximum errors)"},
        ]
    
    def is_config_present(self) -> bool:
        """Check if a configuration file exists in the project."""
        return (
            (self.project_root / "pyrightconfig.json").exists() or
            (self.project_root / "pyproject.toml").exists()
        )


# Singleton instance
_config_manager: Optional[PyrightConfigManager] = None


def get_config_manager(project_root: Optional[str] = None) -> PyrightConfigManager:
    """Get or create the PyrightConfigManager singleton."""
    global _config_manager
    if _config_manager is None and project_root:
        _config_manager = PyrightConfigManager(project_root)
    return _config_manager


def reset_config_manager():
    """Reset the singleton (useful for testing)."""
    global _config_manager
    _config_manager = None
