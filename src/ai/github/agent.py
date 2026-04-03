"""
GitHub Automation Agent for Cortex AI Agent
Automated PR analysis, issue triage, and repository management
"""

import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from PyQt6.QtCore import QObject, pyqtSignal, QThread
import requests
from src.utils.logger import get_logger

log = get_logger("github_agent")


@dataclass
class PullRequest:
    """Represents a GitHub Pull Request."""
    number: int
    title: str
    description: str
    author: str
    branch: str
    files_changed: List[str]
    additions: int
    deletions: int
    created_at: datetime
    labels: List[str]


@dataclass
class Issue:
    """Represents a GitHub Issue."""
    number: int
    title: str
    description: str
    author: str
    labels: List[str]
    state: str
    created_at: datetime
    comments_count: int


class GitHubAgent(QObject):
    """
    GitHub automation agent for repository management.
    
    Features:
    - PR analysis and review
    - Issue triage
    - Documentation generation
    - Translation management
    """
    
    analysis_complete = pyqtSignal(str, dict)  # pr_number, analysis
    issue_triaged = pyqtSignal(str, str)  # issue_number, label
    docs_generated = pyqtSignal(str)  # file_path
    
    def __init__(self, github_token: str = None, repo_owner: str = None, 
                 repo_name: str = None, parent=None):
        super().__init__(parent)
        self.github_token = github_token
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.base_url = "https://api.github.com"
        
        log.info("GitHubAgent initialized")
    
    def set_repository(self, owner: str, name: str):
        """Set target repository."""
        self.repo_owner = owner
        self.repo_name = name
        log.info(f"Repository set: {owner}/{name}")
    
    def set_token(self, token: str):
        """Set GitHub API token."""
        self.github_token = token
        log.info("GitHub token updated")
    
    def _make_request(self, endpoint: str, method: str = "GET", 
                     data: dict = None) -> Optional[dict]:
        """Make authenticated GitHub API request."""
        if not self.github_token:
            log.error("No GitHub token provided")
            return None
        
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        try:
            if method == "GET":
                response = requests.get(url, headers=headers)
            elif method == "POST":
                response = requests.post(url, headers=headers, json=data)
            elif method == "PATCH":
                response = requests.patch(url, headers=headers, json=data)
            else:
                return None
            
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            log.error(f"GitHub API request failed: {e}")
            return None
    
    def analyze_pr(self, pr_number: int) -> Optional[dict]:
        """
        Analyze a pull request.
        
        Args:
            pr_number: PR number
            
        Returns:
            Analysis results
        """
        if not self.repo_owner or not self.repo_name:
            log.error("Repository not set")
            return None
        
        endpoint = f"/repos/{self.repo_owner}/{self.repo_name}/pulls/{pr_number}"
        pr_data = self._make_request(endpoint)
        
        if not pr_data:
            return None
        
        # Get files changed
        files_endpoint = f"/repos/{self.repo_owner}/{self.repo_name}/pulls/{pr_number}/files"
        files_data = self._make_request(files_endpoint)
        
        files_changed = [f["filename"] for f in files_data] if files_data else []
        
        # Create PR object
        pr = PullRequest(
            number=pr_data["number"],
            title=pr_data["title"],
            description=pr_data["body"] or "",
            author=pr_data["user"]["login"],
            branch=pr_data["head"]["ref"],
            files_changed=files_changed,
            additions=pr_data["additions"],
            deletions=pr_data["deletions"],
            created_at=datetime.fromisoformat(pr_data["created_at"].replace("Z", "+00:00")),
            labels=[l["name"] for l in pr_data["labels"]]
        )
        
        # Perform analysis
        analysis = self._perform_pr_analysis(pr)
        
        self.analysis_complete.emit(str(pr_number), analysis)
        log.info(f"PR #{pr_number} analysis complete")
        
        return analysis
    
    def _perform_pr_analysis(self, pr: PullRequest) -> dict:
        """Perform detailed PR analysis."""
        analysis = {
            "pr_number": pr.number,
            "title": pr.title,
            "author": pr.author,
            "summary": {
                "files_changed": len(pr.files_changed),
                "additions": pr.additions,
                "deletions": pr.deletions,
                "total_changes": pr.additions + pr.deletions
            },
            "risk_assessment": self._assess_pr_risk(pr),
            "recommendations": self._generate_pr_recommendations(pr),
            "files_analysis": self._analyze_changed_files(pr.files_changed)
        }
        
        return analysis
    
    def _assess_pr_risk(self, pr: PullRequest) -> str:
        """Assess risk level of PR."""
        total_changes = pr.additions + pr.deletions
        
        if total_changes > 1000:
            return "high"
        elif total_changes > 500:
            return "medium"
        elif len(pr.files_changed) > 20:
            return "medium"
        else:
            return "low"
    
    def _generate_pr_recommendations(self, pr: PullRequest) -> List[str]:
        """Generate recommendations for PR."""
        recommendations = []
        
        if pr.additions + pr.deletions > 1000:
            recommendations.append("Consider breaking this PR into smaller chunks")
        
        if not pr.description:
            recommendations.append("Add a description explaining the changes")
        
        test_files = [f for f in pr.files_changed if "test" in f.lower()]
        if not test_files:
            recommendations.append("Consider adding tests for these changes")
        
        doc_files = [f for f in pr.files_changed if f.endswith(".md")]
        if not doc_files and len(pr.files_changed) > 5:
            recommendations.append("Consider updating documentation")
        
        return recommendations
    
    def _analyze_changed_files(self, files: List[str]) -> dict:
        """Analyze changed file types."""
        analysis = {
            "python_files": len([f for f in files if f.endswith(".py")]),
            "javascript_files": len([f for f in files if f.endswith(".js")]),
            "test_files": len([f for f in files if "test" in f.lower()]),
            "config_files": len([f for f in files if f.endswith((".json", ".yaml", ".yml", ".toml"))]),
            "doc_files": len([f for f in files if f.endswith(".md")])
        }
        return analysis
    
    def triage_issue(self, issue_number: int) -> Optional[str]:
        """
        Triage an issue and suggest labels.
        
        Args:
            issue_number: Issue number
            
        Returns:
            Suggested label
        """
        if not self.repo_owner or not self.repo_name:
            return None
        
        endpoint = f"/repos/{self.repo_owner}/{self.repo_name}/issues/{issue_number}"
        issue_data = self._make_request(endpoint)
        
        if not issue_data:
            return None
        
        issue = Issue(
            number=issue_data["number"],
            title=issue_data["title"],
            description=issue_data["body"] or "",
            author=issue_data["user"]["login"],
            labels=[l["name"] for l in issue_data["labels"]],
            state=issue_data["state"],
            created_at=datetime.fromisoformat(issue_data["created_at"].replace("Z", "+00:00")),
            comments_count=issue_data["comments"]
        )
        
        # Determine label
        suggested_label = self._determine_issue_label(issue)
        
        self.issue_triaged.emit(str(issue_number), suggested_label)
        log.info(f"Issue #{issue_number} triaged as: {suggested_label}")
        
        return suggested_label
    
    def _determine_issue_label(self, issue: Issue) -> str:
        """Determine appropriate label for issue."""
        title_lower = issue.title.lower()
        desc_lower = issue.description.lower()
        
        # Check for bug-related keywords
        bug_keywords = ["bug", "error", "crash", "fix", "broken", "not working"]
        if any(kw in title_lower for kw in bug_keywords):
            return "bug"
        
        # Check for feature requests
        feature_keywords = ["feature", "enhancement", "add", "implement", "support"]
        if any(kw in title_lower for kw in feature_keywords):
            return "enhancement"
        
        # Check for documentation
        doc_keywords = ["doc", "readme", "documentation", "wiki"]
        if any(kw in title_lower for kw in doc_keywords):
            return "documentation"
        
        # Default
        return "triage"
    
    def generate_documentation(self, code_files: List[str], 
                              output_path: str = "docs/API.md") -> bool:
        """
        Generate documentation from code files.
        
        Args:
            code_files: List of code files to document
            output_path: Output path for documentation
            
        Returns:
            True if successful
        """
        try:
            doc_content = ["# API Documentation\n\n"]
            doc_content.append(f"Generated: {datetime.now().isoformat()}\n\n")
            
            for file_path in code_files:
                doc_content.append(f"## {file_path}\n\n")
                doc_content.append("```python\n")
                # In real implementation, would analyze code structure
                doc_content.append(f"# Code from {file_path}\n")
                doc_content.append("```\n\n")
            
            # Write to file
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("".join(doc_content))
            
            self.docs_generated.emit(output_path)
            log.info(f"Documentation generated: {output_path}")
            return True
            
        except Exception as e:
            log.error(f"Documentation generation failed: {e}")
            return False
    
    def get_open_prs(self) -> List[dict]:
        """Get list of open pull requests."""
        if not self.repo_owner or not self.repo_name:
            return []
        
        endpoint = f"/repos/{self.repo_owner}/{self.repo_name}/pulls?state=open"
        return self._make_request(endpoint) or []
    
    def get_open_issues(self) -> List[dict]:
        """Get list of open issues."""
        if not self.repo_owner or not self.repo_name:
            return []
        
        endpoint = f"/repos/{self.repo_owner}/{self.repo_name}/issues?state=open"
        return self._make_request(endpoint) or []
    
    def create_comment(self, pr_number: int, comment: str) -> bool:
        """Add comment to PR."""
        if not self.repo_owner or not self.repo_name:
            return False
        
        endpoint = f"/repos/{self.repo_owner}/{self.repo_name}/issues/{pr_number}/comments"
        result = self._make_request(endpoint, method="POST", data={"body": comment})
        
        if result:
            log.info(f"Comment added to PR #{pr_number}")
            return True
        return False
    
    def add_label(self, issue_number: int, label: str) -> bool:
        """Add label to issue/PR."""
        if not self.repo_owner or not self.repo_name:
            return False
        
        endpoint = f"/repos/{self.repo_owner}/{self.repo_name}/issues/{issue_number}/labels"
        result = self._make_request(endpoint, method="POST", data={"labels": [label]})
        
        if result:
            log.info(f"Label '{label}' added to issue #{issue_number}")
            return True
        return False


# Global instance
_github_agent: Optional[GitHubAgent] = None


def get_github_agent(token: str = None, owner: str = None, 
                     repo: str = None) -> GitHubAgent:
    """Get global GitHubAgent instance."""
    global _github_agent
    if _github_agent is None:
        _github_agent = GitHubAgent(token, owner, repo)
    return _github_agent
