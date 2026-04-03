"""
Skill System for Cortex AI Agent
Extensible capabilities through skill plugins
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from PyQt6.QtCore import QObject, pyqtSignal
from src.utils.logger import get_logger

log = get_logger("skill_system")


@dataclass
class SkillCapability:
    """Represents a capability provided by a skill."""
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillDefinition:
    """Definition of a skill."""
    id: str
    name: str
    version: str
    description: str
    author: str
    capabilities: List[SkillCapability] = field(default_factory=list)


class Skill(QObject):
    """Base class for all skills."""
    
    capability_invoked = pyqtSignal(str, Any)
    
    def __init__(self, definition: SkillDefinition, parent=None):
        super().__init__(parent)
        self.definition = definition
        self._initialized = False
        
    def initialize(self, context: Dict[str, Any]) -> bool:
        """Initialize the skill with context."""
        self._initialized = True
        log.info(f"Skill {self.definition.name} initialized")
        return True
    
    def execute(self, capability_name: str, params: Dict[str, Any]) -> Any:
        """Execute a capability."""
        raise NotImplementedError("Subclasses must implement execute()")
    
    def get_capabilities(self) -> List[SkillCapability]:
        """Get list of capabilities provided by this skill."""
        return self.definition.capabilities
    
    def shutdown(self):
        """Clean up resources."""
        self._initialized = False


class CodeAnalysisSkill(Skill):
    """Built-in skill for code analysis."""
    
    def __init__(self, parent=None):
        definition = SkillDefinition(
            id="builtin.code_analysis",
            name="Code Analysis",
            version="1.0.0",
            description="Analyze code for patterns, complexity, and issues",
            author="Cortex Team",
            capabilities=[
                SkillCapability(
                    name="analyze_complexity",
                    description="Calculate cyclomatic complexity",
                    parameters={"code": "string"}
                ),
                SkillCapability(
                    name="find_patterns",
                    description="Find code patterns",
                    parameters={"code": "string", "pattern": "string"}
                )
            ]
        )
        super().__init__(definition, parent)
    
    def execute(self, capability_name: str, params: Dict[str, Any]) -> Any:
        """Execute code analysis capability."""
        if capability_name == "analyze_complexity":
            code = params.get("code", "")
            complexity = 1 + code.count('if ') + code.count('for ')
            return {"complexity": complexity, "rating": "low" if complexity < 5 else "high"}
        elif capability_name == "find_patterns":
            code = params.get("code", "")
            pattern = params.get("pattern", "")
            return [{"line": i, "match": pattern} for i, line in enumerate(code.split('\n'), 1) if pattern in line]
        else:
            raise ValueError(f"Unknown capability: {capability_name}")


class SkillRegistry(QObject):
    """Registry for managing skills."""
    
    skill_registered = pyqtSignal(str)
    skill_unregistered = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._skills: Dict[str, Skill] = {}
        self._register_builtin_skills()
        log.info("SkillRegistry initialized")
    
    def _register_builtin_skills(self):
        """Register built-in skills."""
        self.register_skill(CodeAnalysisSkill())
        log.info("Built-in skills registered")
    
    def register_skill(self, skill: Skill) -> bool:
        """Register a skill."""
        if skill.definition.id in self._skills:
            log.warning(f"Skill {skill.definition.id} already registered")
            return False
        
        self._skills[skill.definition.id] = skill
        self.skill_registered.emit(skill.definition.id)
        log.info(f"Registered skill: {skill.definition.name}")
        return True
    
    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """Get a skill by ID."""
        return self._skills.get(skill_id)
    
    def list_skills(self) -> List[Dict[str, Any]]:
        """List all registered skills."""
        return [
            {
                "id": skill.definition.id,
                "name": skill.definition.name,
                "version": skill.definition.version,
                "capabilities": [c.name for c in skill.definition.capabilities]
            }
            for skill in self._skills.values()
        ]
    
    def execute_capability(self, skill_id: str, capability_name: str, params: Dict[str, Any]) -> Any:
        """Execute a capability from a skill."""
        skill = self._skills.get(skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")
        
        result = skill.execute(capability_name, params)
        try:
            skill.capability_invoked.emit(capability_name, result)
        except TypeError:
            # Signal type mismatch, ignore
            pass
        return result


# Global instance
_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    """Get global SkillRegistry instance."""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry
