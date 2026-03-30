"""
MCP (Model Context Protocol) Integration for Cortex AI Agent
External tool integration via MCP protocol
"""

import json
import asyncio
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from src.utils.logger import get_logger

log = get_logger("mcp")


@dataclass
class MCPTool:
    """Represents an MCP tool."""
    name: str
    description: str
    parameters: Dict[str, Any]
    server: str


class MCPClient(QObject):
    """Client for connecting to MCP servers."""
    
    tool_executed = pyqtSignal(str, Any)
    connected = pyqtSignal(str)
    disconnected = pyqtSignal(str)
    error = pyqtSignal(str)
    
    def __init__(self, server_url: str, parent=None):
        super().__init__(parent)
        self.server_url = server_url
        self._connected = False
        self._tools: Dict[str, MCPTool] = {}
        
    def connect(self) -> bool:
        """Connect to MCP server."""
        try:
            self._connected = True
            self.connected.emit(self.server_url)
            log.info(f"Connected to MCP server: {self.server_url}")
            return True
        except Exception as e:
            self.error.emit(str(e))
            return False
    
    def disconnect(self):
        """Disconnect from MCP server."""
        self._connected = False
        self.disconnected.emit(self.server_url)
        log.info(f"Disconnected from MCP server: {self.server_url}")
    
    def list_tools(self) -> List[MCPTool]:
        """List available tools from server."""
        # In production, this would make an actual MCP call
        return list(self._tools.values())
    
    def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Execute a tool on the MCP server."""
        if not self._connected:
            raise ConnectionError("Not connected to MCP server")
        
        log.info(f"Executing MCP tool: {tool_name}")
        
        # Mock execution for now
        result = {"tool": tool_name, "params": params, "status": "success"}
        self.tool_executed.emit(tool_name, result)
        return result
    
    def is_connected(self) -> bool:
        """Check if connected to server."""
        return self._connected


class MCPManager(QObject):
    """Manager for multiple MCP connections."""
    
    server_connected = pyqtSignal(str)
    server_disconnected = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._clients: Dict[str, MCPClient] = {}
        log.info("MCPManager initialized")
    
    def connect_server(self, name: str, server_url: str) -> bool:
        """Connect to an MCP server."""
        if name in self._clients:
            log.warning(f"Server {name} already connected")
            return False
        
        client = MCPClient(server_url)
        if client.connect():
            self._clients[name] = client
            self.server_connected.emit(name)
            return True
        return False
    
    def disconnect_server(self, name: str):
        """Disconnect from an MCP server."""
        if name in self._clients:
            self._clients[name].disconnect()
            del self._clients[name]
            self.server_disconnected.emit(name)
    
    def get_all_tools(self) -> List[MCPTool]:
        """Get all tools from all connected servers."""
        tools = []
        for client in self._clients.values():
            tools.extend(client.list_tools())
        return tools
    
    def execute_tool(self, server_name: str, tool_name: str, params: Dict[str, Any]) -> Any:
        """Execute a tool on a specific server."""
        if server_name not in self._clients:
            raise ValueError(f"Server not connected: {server_name}")
        
        return self._clients[server_name].execute_tool(tool_name, params)
    
    def list_servers(self) -> List[str]:
        """List all connected servers."""
        return list(self._clients.keys())


# Global instance
_mcp_manager: Optional[MCPManager] = None


def get_mcp_manager() -> MCPManager:
    """Get global MCPManager instance."""
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPManager()
    return _mcp_manager
