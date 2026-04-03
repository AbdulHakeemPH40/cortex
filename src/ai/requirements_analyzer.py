"""
Requirements Analyzer for Autonomous AI Agent
Parses .md design documents and extracts structured requirements for autonomous development.
"""

import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import logging

log = logging.getLogger(__name__)


class RequirementType(Enum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    TECHNICAL = "technical"
    API = "api"
    DATA_MODEL = "data_model"
    CONSTRAINT = "constraint"


class ArchitecturePattern(Enum):
    MVC = "MVC"
    MICROSERVICES = "microservices"
    SERVERLESS = "serverless"
    EVENT_DRIVEN = "event_driven"
    LAYERED = "layered"
    CLEAN = "clean_architecture"


@dataclass
class Feature:
    """Represents a feature extracted from requirements"""
    name: str
    description: str
    priority: str = "medium"  # high, medium, low
    user_stories: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)


@dataclass
class UserStory:
    """User story with standard format"""
    title: str
    as_a: str  # role
    i_want: str  # goal
    so_that: str  # benefit
    acceptance_criteria: List[str] = field(default_factory=list)
    status: str = "pending"  # pending, in_progress, done


@dataclass
class TechStack:
    """Technology stack preferences"""
    languages: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    databases: List[str] = field(default_factory=list)
    cloud_providers: List[str] = field(default_factory=list)
    devops_tools: List[str] = field(default_factory=list)
    testing_frameworks: List[str] = field(default_factory=list)


@dataclass
class APIEndpoint:
    """API endpoint specification"""
    method: str  # GET, POST, PUT, DELETE, PATCH
    path: str
    description: str
    request_body: Optional[Dict[str, Any]] = None
    response_schema: Optional[Dict[str, Any]] = None
    authentication: bool = True
    rate_limit: Optional[int] = None


@dataclass
class DataModel:
    """Data entity/model specification"""
    name: str
    fields: Dict[str, str]  # field_name -> type
    relationships: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    indexes: List[str] = field(default_factory=list)


@dataclass
class Constraint:
    """Project constraint (performance, security, etc.)"""
    category: str  # performance, security, compliance, budget, timeline
    description: str
    metric: Optional[str] = None  # e.g., "< 200ms latency"
    priority: str = "high"


@dataclass
class Architecture:
    """System architecture blueprint"""
    pattern: ArchitecturePattern
    components: List[Dict[str, str]]
    data_flow: str
    deployment_strategy: str
    scaling_approach: str


@dataclass
class RequirementsDocument:
    """Complete parsed requirements document"""
    title: str
    version: str
    features: List[Feature] = field(default_factory=list)
    user_stories: List[UserStory] = field(default_factory=list)
    tech_stack: Optional[TechStack] = None
    api_endpoints: List[APIEndpoint] = field(default_factory=list)
    data_models: List[DataModel] = field(default_factory=list)
    constraints: List[Constraint] = field(default_factory=list)
    architecture: Optional[Architecture] = None
    missing_requirements: List[str] = field(default_factory=list)
    clarifying_questions: List[str] = field(default_factory=list)


class RequirementsAnalyzer:
    """
    Analyzes .md design documents and extracts structured requirements.
    Enables autonomous AI agents to understand project specifications.
    """
    
    def __init__(self):
        self.content = ""
        self.sections = {}
        
    def parse_file(self, file_path: str) -> RequirementsDocument:
        """Parse a .md file and extract requirements"""
        log.info(f"Parsing requirements from: {file_path}")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.content = f.read()
        except Exception as e:
            log.error(f"Failed to read file: {e}")
            raise
        
        return self.parse_content(self.content)
    
    def parse_content(self, content: str) -> RequirementsDocument:
        """Parse markdown content string"""
        self.content = content
        self._extract_sections()
        
        # Extract all components
        doc = RequirementsDocument(
            title=self._extract_title(),
            version=self._extract_version()
        )
        
        doc.features = self._extract_features()
        doc.user_stories = self._extract_user_stories()
        doc.tech_stack = self._identify_tech_stack()
        doc.api_endpoints = self._extract_api_endpoints()
        doc.data_models = self._extract_data_models()
        doc.constraints = self._detect_constraints()
        doc.architecture = self._infer_architecture()
        
        # Perform gap analysis
        doc.missing_requirements, doc.clarifying_questions = self._perform_gap_analysis(doc)
        
        log.info(f"✅ Parsed {len(doc.features)} features, {len(doc.user_stories)} user stories")
        log.info(f"   Found {len(doc.api_endpoints)} API endpoints, {len(doc.data_models)} data models")
        
        if doc.missing_requirements:
            log.warning(f"   ⚠️ Missing: {len(doc.missing_requirements)} requirements gaps detected")
        if doc.clarifying_questions:
            log.info(f"   ❓ {len(doc.clarifying_questions)} clarifying questions generated")
        
        return doc
    
    def _extract_sections(self) -> None:
        """Split content into sections based on headers"""
        # Match markdown headers (#, ##, ###, etc.)
        pattern = r'^(#{1,6})\s+(.+)$'
        current_section = "introduction"
        current_content = []
        
        for line in self.content.split('\n'):
            match = re.match(pattern, line)
            if match:
                # Save previous section
                if current_content:
                    self.sections[current_section] = '\n'.join(current_content)
                # Start new section
                level = len(match.group(1))
                current_section = f"{'#' * level}_{match.group(2).strip().lower().replace(' ', '_')}"
                current_content = []
            else:
                current_content.append(line)
        
        # Save last section
        if current_content:
            self.sections[current_section] = '\n'.join(current_content)
    
    def _extract_title(self) -> str:
        """Extract document title from first H1 or filename"""
        h1_match = re.search(r'^#\s+(.+)$', self.content, re.MULTILINE)
        if h1_match:
            return h1_match.group(1).strip()
        return "Untitled Project"
    
    def _extract_version(self) -> str:
        """Extract version from document"""
        version_match = re.search(r'[Vv]ersion[:\s]+([0-9.]+)', self.content)
        if version_match:
            return version_match.group(1)
        return "1.0"
    
    def _extract_features(self) -> List[Feature]:
        """Extract features from content"""
        features = []
        
        # Look for feature sections
        feature_patterns = [
            r'##\s+Features?\s*\n([\s\S]*?)(?=##|$)',
            r'###\s+Features?\s*\n([\s\S]*?)(?=###|$)',
            r'-\s*\[x?\]\s*Feature[:\s]+(.+?)(?=\n\n|\Z)',
            r'\*\*Feature\*\*[:\s]+(.+?)(?=\n\n|\Z)'
        ]
        
        for pattern in feature_patterns:
            matches = re.finditer(pattern, self.content, re.IGNORECASE)
            for match in matches:
                feature_text = match.group(0)
                
                # Extract feature name
                name_match = re.search(r'(?:Feature|###)\s*[:\-]?\s*(.+?)(?:\n|$)', feature_text)
                if not name_match:
                    continue
                    
                name = name_match.group(1).strip()
                
                # Extract description
                desc_match = re.search(r'(?:description|purpose)[:\s]+(.+?)(?=\n[A-Z]|\*\*|\Z)', 
                                      feature_text, re.IGNORECASE)
                description = desc_match.group(1).strip() if desc_match else name
                
                # Extract priority
                priority_match = re.search(r'(high|medium|low)\s*priority', feature_text, re.IGNORECASE)
                priority = priority_match.group(1).lower() if priority_match else "medium"
                
                # Extract user stories
                stories = re.findall(r'(?:As a|As an)\s+([^,.]+),?\s*(?:I want|I need)\s+([^,.]+),?\s*(?:so that|to)\s+([^.\n]+)', 
                                   feature_text, re.IGNORECASE)
                
                feature = Feature(
                    name=name,
                    description=description,
                    priority=priority,
                    user_stories=[f"As a {s[0]}, I want {s[1]}, so that {s[2]}" for s in stories]
                )
                
                features.append(feature)
        
        return features
    
    def _extract_user_stories(self) -> List[UserStory]:
        """Extract user stories in standard format"""
        user_stories = []
        
        # Pattern: "As a [role], I want [goal], so that [benefit]"
        pattern = r'(?:As a|As an)\s+([^,.]+),?\s*(?:I want|I need)\s+([^,.]+),?\s*(?:so that|to)\s+([^.\n]+)'
        
        matches = re.finditer(pattern, self.content, re.IGNORECASE)
        for match in matches:
            story = UserStory(
                title=f"{match.group(1).strip()} - {match.group(2).strip()}",
                as_a=match.group(1).strip(),
                i_want=match.group(2).strip(),
                so_that=match.group(3).strip()
            )
            
            # Try to find acceptance criteria nearby
            story_text = self.content[max(0, match.start()-200):min(len(self.content), match.end()+500)]
            criteria_matches = re.findall(r'(?:Given|When|Then|And)\s+[^.\n]+', story_text, re.IGNORECASE)
            story.acceptance_criteria = criteria_matches[:5]  # Limit to 5
            
            user_stories.append(story)
        
        return user_stories
    
    def _identify_tech_stack(self) -> TechStack:
        """Identify technology stack preferences"""
        tech_stack = TechStack()
        
        # Language patterns
        lang_patterns = [
            r'(Python|JavaScript|TypeScript|Java|Rust|Go|C#|C\+\+|Ruby|PHP|Swift|Kotlin)',
            r'(frontend|backend|full[- ]stack)\s*:?\s*([\w\s,]+)'
        ]
        
        # Framework patterns
        framework_patterns = [
            r'(React|Vue\.?js?|Angular|Svelte|Next\.?js|Nuxt\.?js)',
            r'(Django|Flask|FastAPI|Express|NestJS|Spring|Laravel)',
            r'(Node\.?js|Deno|Bun)',
            r'(TensorFlow|PyTorch|scikit-learn)'
        ]
        
        # Database patterns
        db_patterns = [
            r'(PostgreSQL|MySQL|MongoDB|Redis|SQLite|Elasticsearch|Cassandra)',
            r'(Firebase|Supabase|PlanetScale)'
        ]
        
        # Cloud patterns
        cloud_patterns = [
            r'(AWS|Azure|GCP|Google Cloud|Alibaba Cloud)',
            r'(EC2|Lambda|S3|CloudFront|RDS)'
        ]
        
        # DevOps patterns
        devops_patterns = [
            r'(Docker|Kubernetes|Terraform|Ansible|Jenkins|GitHub Actions|GitLab CI)',
            r'(Prometheus|Grafana|ELK Stack|Datadog)'
        ]
        
        def extract_matches(patterns, text):
            results = []
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                # Handle tuples from groups
                for match in matches:
                    if isinstance(match, tuple):
                        # Take first non-empty group
                        for group in match:
                            if group and isinstance(group, str):
                                results.append(group.strip())
                                break
                    elif isinstance(match, str):
                        results.append(match.strip())
            return list(set(results))
        
        # Search entire content
        tech_stack.languages = extract_matches(lang_patterns, self.content)
        tech_stack.frameworks = extract_matches(framework_patterns, self.content)
        tech_stack.databases = extract_matches(db_patterns, self.content)
        tech_stack.cloud_providers = extract_matches(cloud_patterns, self.content)
        tech_stack.devops_tools = extract_matches(devops_patterns, self.content)
        
        return tech_stack
    
    def _extract_api_endpoints(self) -> List[APIEndpoint]:
        """Extract API endpoint specifications"""
        endpoints = []
        
        # Pattern: METHOD /path - description
        pattern = r'(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)\s*[-:]?\s*([^\n]+)'
        
        matches = re.finditer(pattern, self.content, re.IGNORECASE)
        for match in matches:
            endpoint = APIEndpoint(
                method=match.group(1).upper(),
                path=match.group(2),
                description=match.group(3).strip()
            )
            endpoints.append(endpoint)
        
        return endpoints
    
    def _extract_data_models(self) -> List[DataModel]:
        """Extract data model/entity definitions"""
        models = []
        
        # Look for schema definitions
        schema_pattern = r'(?:schema|model|entity|table)[:\s]+(\w+)[\s\S]*?(?=(?:schema|model|entity|table)[:\s]|\Z)'
        
        matches = re.finditer(schema_pattern, self.content, re.IGNORECASE)
        for match in matches:
            model_text = match.group(0)
            model_name = match.group(1)
            
            # Extract fields (simple pattern: field_name: type)
            fields = {}
            field_matches = re.findall(r'(\w+)\s*:\s*(\w+)', model_text)
            fields = dict(field_matches)
            
            if fields:
                model = DataModel(
                    name=model_name,
                    fields=fields
                )
                models.append(model)
        
        return models
    
    def _detect_constraints(self) -> List[Constraint]:
        """Detect project constraints"""
        constraints = []
        
        # Performance constraints
        perf_matches = re.finditer(
            r'(performance|latency|response time|throughput)[:\s]+([^\n]+)',
            self.content, re.IGNORECASE
        )
        for match in perf_matches:
            constraints.append(Constraint(
                category="performance",
                description=match.group(2).strip(),
                metric=match.group(2)
            ))
        
        # Security constraints
        sec_matches = re.finditer(
            r'(security|authentication|authorization|encryption)[:\s]+([^\n]+)',
            self.content, re.IGNORECASE
        )
        for match in sec_matches:
            constraints.append(Constraint(
                category="security",
                description=match.group(2).strip()
            ))
        
        return constraints
    
    def _infer_architecture(self) -> Optional[Architecture]:
        """Infer architecture pattern from requirements"""
        content_lower = self.content.lower()
        
        # Detect architecture pattern
        if 'microservice' in content_lower:
            pattern = ArchitecturePattern.MICROSERVICES
        elif 'serverless' in content_lower or 'lambda' in content_lower:
            pattern = ArchitecturePattern.SERVERLESS
        elif 'event' in content_lower and ('driven' in content_lower or 'queue' in content_lower):
            pattern = ArchitecturePattern.EVENT_DRIVEN
        elif 'mvc' in content_lower or 'model-view' in content_lower:
            pattern = ArchitecturePattern.MVC
        else:
            pattern = ArchitecturePattern.LAYERED  # Default
        
        # Simple component extraction
        components = []
        comp_matches = re.finditer(r'(?:component|module|service)[:\s]+(\w+)', self.content, re.IGNORECASE)
        for match in comp_matches:
            components.append({"name": match.group(1)})
        
        if components:
            return Architecture(
                pattern=pattern,
                components=components,
                data_flow="Request → Controller → Service → Repository → Database",
                deployment_strategy="Container-based (Docker)",
                scaling_approach="Horizontal scaling with load balancer"
            )
        
        return None
    
    def _perform_gap_analysis(self, doc: RequirementsDocument) -> tuple:
        """Identify missing requirements and generate clarifying questions"""
        missing = []
        questions = []
        
        # Check for common gaps
        if not doc.tech_stack or not doc.tech_stack.languages:
            missing.append("No programming language specified")
            questions.append("What programming language(s) should be used?")
        
        if not doc.tech_stack or not doc.tech_stack.frameworks:
            missing.append("No framework preferences identified")
            questions.append("Which frameworks do you prefer for this project?")
        
        if not doc.data_models and doc.features:
            missing.append("No data models defined despite having features")
            questions.append("What data entities are needed to support these features?")
        
        if not doc.api_endpoints and any('web' in f.description.lower() or 'api' in f.description.lower() 
                                         for f in doc.features):
            missing.append("API endpoints not defined for web/API features")
            questions.append("Can you specify the API endpoints needed?")
        
        # Check for missing non-functional requirements
        if not any(c.category == "security" for c in doc.constraints):
            missing.append("No security requirements specified")
            questions.append("Are there specific security requirements (auth, encryption, compliance)?")
        
        if not any(c.category == "performance" for c in doc.constraints):
            missing.append("No performance requirements specified")
            questions.append("What are the performance expectations (latency, throughput)?")
        
        # Check for missing testing requirements
        if 'test' not in self.content.lower():
            missing.append("No testing strategy mentioned")
            questions.append("What testing approach do you want? (unit tests, integration tests, E2E)")
        
        # Check for missing deployment requirements
        if not any(term in self.content.lower() for term in ['deploy', 'docker', 'kubernetes', 'ci/cd']):
            missing.append("No deployment strategy specified")
            questions.append("How should this application be deployed? (Docker, cloud, on-premise)")
        
        return missing, questions


def analyze_requirements(file_path: str) -> RequirementsDocument:
    """Convenience function to analyze requirements from a file"""
    analyzer = RequirementsAnalyzer()
    return analyzer.parse_file(file_path)


def analyze_requirements_content(content: str) -> RequirementsDocument:
    """Convenience function to analyze requirements from content string"""
    analyzer = RequirementsAnalyzer()
    return analyzer.parse_content(content)
