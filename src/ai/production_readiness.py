"""
Production Readiness Checklist & Deployment Automation
Ensures code is production-ready with comprehensive checks and IaC generation.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import logging
import json

log = logging.getLogger(__name__)


class CheckStatus(Enum):
    PASS = "✅ PASS"
    FAIL = "❌ FAIL"
    WARNING = "⚠️ WARNING"
    NOT_APPLICABLE = "Ⓜ️ N/A"


@dataclass
class ChecklistItem:
    """Individual checklist item."""
    category: str
    name: str
    description: str
    status: CheckStatus
    details: Optional[str] = None
    auto_fixable: bool = False
    auto_fixed: bool = False


@dataclass
class ProductionReadinessReport:
    """Complete production readiness assessment."""
    overall_status: CheckStatus
    total_checks: int
    passed: int
    failed: int
    warnings: int
    items: List[ChecklistItem]
    deployment_artifacts: List[str]
    recommendations: List[str]
    
    def to_markdown(self) -> str:
        """Generate markdown report."""
        md = f"""# Production Readiness Report

## Summary
- **Overall Status**: {self.overall_status.value}
- **Total Checks**: {self.total_checks}
- **Passed**: {self.passed} ({self.passed/self.total_checks*100:.1f}%)
- **Failed**: {self.failed}
- **Warnings**: {self.warnings}

## Detailed Results

"""
        
        # Group by category
        categories = {}
        for item in self.items:
            if item.category not in categories:
                categories[item.category] = []
            categories[item.category].append(item)
        
        for category, items in categories.items():
            md += f"### {category}\n\n"
            for item in items:
                status_icon = item.status.value.split()[0]
                md += f"- {status_icon} **{item.name}**: {item.description}\n"
                if item.details:
                    md += f"  - {item.details}\n"
            md += "\n"
        
        if self.recommendations:
            md += "## Recommendations\n\n"
            for i, rec in enumerate(self.recommendations, 1):
                md += f"{i}. {rec}\n"
        
        if self.deployment_artifacts:
            md += "\n## Generated Artifacts\n\n"
            for artifact in self.deployment_artifacts:
                md += f"- 📄 `{artifact}`\n"
        
        return md


class ProductionReadinessChecker:
    """
    Comprehensive production readiness verification.
    
    Checks across 8 critical dimensions:
    1. Code Quality
    2. Security
    3. Performance
    4. Testing
    5. Observability
    6. Deployment
    7. Documentation
    8. Compliance
    """
    
    def __init__(self):
        self.checklist = []
        self.artifacts_generated = []
    
    def assess_readiness(self, project_context: Dict[str, Any]) -> ProductionReadinessReport:
        """
        Perform comprehensive production readiness assessment.
        
        Args:
            project_context: Project information including code, tests, configs
        
        Returns:
            ProductionReadinessReport with findings
        """
        log.info("🔍 Starting production readiness assessment...")
        
        self.checklist = []
        self.artifacts_generated = []
        
        # Run all checks
        self._check_code_quality(project_context)
        self._check_security(project_context)
        self._check_performance(project_context)
        self._check_testing(project_context)
        self._check_observability(project_context)
        self._check_deployment(project_context)
        self._check_documentation(project_context)
        self._check_compliance(project_context)
        
        # Calculate summary
        passed = sum(1 for item in self.checklist if item.status == CheckStatus.PASS)
        failed = sum(1 for item in self.checklist if item.status == CheckStatus.FAIL)
        warnings = sum(1 for item in self.checklist if item.status == CheckStatus.WARNING)
        
        # Determine overall status
        if failed > 0:
            overall = CheckStatus.FAIL
        elif warnings > 0:
            overall = CheckStatus.WARNING
        else:
            overall = CheckStatus.PASS
        
        # Generate recommendations
        recommendations = self._generate_recommendations()
        
        report = ProductionReadinessReport(
            overall_status=overall,
            total_checks=len(self.checklist),
            passed=passed,
            failed=failed,
            warnings=warnings,
            items=self.checklist,
            deployment_artifacts=self.artifacts_generated,
            recommendations=recommendations
        )
        
        log.info(f"   ✅ Assessment complete: {passed}/{len(self.checklist)} checks passed")
        
        return report
    
    def _add_check(self, category: str, name: str, description: str,
                   status: CheckStatus, details: str = None, 
                   auto_fixable: bool = False) -> None:
        """Add a checklist item."""
        self.checklist.append(ChecklistItem(
            category=category,
            name=name,
            description=description,
            status=status,
            details=details,
            auto_fixable=auto_fixable
        ))
    
    def _check_code_quality(self, context: Dict) -> None:
        """Check code quality metrics."""
        log.debug("   Checking code quality...")
        
        # Check for linting
        has_linting = context.get("has_linting", False)
        self._add_check(
            "Code Quality",
            "Linting",
            "Code passes linter checks",
            CheckStatus.PASS if has_linting else CheckStatus.FAIL,
            "ESLint/Pylint configured" if has_linting else "No linter configured",
            auto_fixable=True
        )
        
        # Check code complexity
        avg_complexity = context.get("avg_complexity", 0)
        if avg_complexity < 10:
            status = CheckStatus.PASS
            details = f"Average complexity: {avg_complexity}"
        elif avg_complexity < 20:
            status = CheckStatus.WARNING
            details = f"Complexity slightly high: {avg_complexity}"
        else:
            status = CheckStatus.FAIL
            details = f"Complexity too high: {avg_complexity}"
        
        self._add_check(
            "Code Quality",
            "Complexity",
            "Cyclomatic complexity within limits",
            status,
            details
        )
        
        # Check code duplication
        duplication_pct = context.get("code_duplication_pct", 0)
        if duplication_pct < 5:
            status = CheckStatus.PASS
        elif duplication_pct < 10:
            status = CheckStatus.WARNING
        else:
            status = CheckStatus.FAIL
        
        self._add_check(
            "Code Quality",
            "Duplication",
            "Code duplication below threshold",
            status,
            f"{duplication_pct}% duplicated code"
        )
        
        # Check for type hints
        has_types = context.get("has_type_hints", False)
        self._add_check(
            "Code Quality",
            "Type Safety",
            "Type hints/annotations present",
            CheckStatus.PASS if has_types else CheckStatus.WARNING,
            "Full type coverage" if has_types else "Missing type hints"
        )
    
    def _check_security(self, context: Dict) -> None:
        """Check security requirements."""
        log.debug("   Checking security...")
        
        # Authentication
        has_auth = context.get("has_authentication", False)
        self._add_check(
            "Security",
            "Authentication",
            "Authentication mechanism implemented",
            CheckStatus.PASS if has_auth else CheckStatus.FAIL,
            "OAuth2/JWT configured" if has_auth else "No auth found"
        )
        
        # Input validation
        has_validation = context.get("has_input_validation", False)
        self._add_check(
            "Security",
            "Input Validation",
            "Input sanitization implemented",
            CheckStatus.PASS if has_validation else CheckStatus.FAIL,
            auto_fixable=True
        )
        
        # Secrets management
        uses_env_vars = context.get("uses_environment_variables", False)
        self._add_check(
            "Security",
            "Secrets Management",
            "Sensitive data in environment variables",
            CheckStatus.PASS if uses_env_vars else CheckStatus.FAIL,
            ".env configuration" if uses_env_vars else "Hardcoded secrets detected"
        )
        
        # Security headers (for web apps)
        has_security_headers = context.get("has_security_headers", False)
        if context.get("is_web_app", False):
            self._add_check(
                "Security",
                "Security Headers",
                "HTTP security headers configured",
                CheckStatus.PASS if has_security_headers else CheckStatus.WARNING,
                "CORS, CSP, HSTS" if has_security_headers else "Missing headers"
            )
    
    def _check_performance(self, context: Dict) -> None:
        """Check performance optimizations."""
        log.debug("   Checking performance...")
        
        # Caching
        has_caching = context.get("has_caching", False)
        self._add_check(
            "Performance",
            "Caching Strategy",
            "Appropriate caching implemented",
            CheckStatus.PASS if has_caching else CheckStatus.WARNING,
            "Redis/Memcached" if has_caching else "No caching detected",
            auto_fixable=True
        )
        
        # Database indexing
        has_indexes = context.get("has_database_indexes", False)
        self._add_check(
            "Performance",
            "Database Indexing",
            "Database queries optimized with indexes",
            CheckStatus.PASS if has_indexes else CheckStatus.WARNING,
            auto_fixable=True
        )
        
        # Response time
        avg_response_time = context.get("avg_response_time_ms", 0)
        if avg_response_time < 200:
            status = CheckStatus.PASS
            details = f"{avg_response_time}ms average"
        elif avg_response_time < 500:
            status = CheckStatus.WARNING
            details = f"{avg_response_time}ms (target: <200ms)"
        else:
            status = CheckStatus.FAIL
            details = f"{avg_response_time}ms (too slow)"
        
        self._add_check(
            "Performance",
            "Response Time",
            "Response time within acceptable limits",
            status,
            details
        )
    
    def _check_testing(self, context: Dict) -> None:
        """Check testing coverage."""
        log.debug("   Checking testing...")
        
        # Test coverage
        coverage_pct = context.get("test_coverage_pct", 0)
        if coverage_pct >= 80:
            status = CheckStatus.PASS
        elif coverage_pct >= 60:
            status = CheckStatus.WARNING
        else:
            status = CheckStatus.FAIL
        
        self._add_check(
            "Testing",
            "Test Coverage",
            "Code coverage ≥ 80%",
            status,
            f"{coverage_pct}% coverage",
            auto_fixable=True
        )
        
        # Unit tests
        has_unit_tests = context.get("has_unit_tests", False)
        self._add_check(
            "Testing",
            "Unit Tests",
            "Unit tests for all functions",
            CheckStatus.PASS if has_unit_tests else CheckStatus.FAIL,
            auto_fixable=True
        )
        
        # Integration tests
        has_integration_tests = context.get("has_integration_tests", False)
        self._add_check(
            "Testing",
            "Integration Tests",
            "Integration tests for APIs/services",
            CheckStatus.PASS if has_integration_tests else CheckStatus.WARNING,
            auto_fixable=True
        )
        
        # E2E tests
        has_e2e_tests = context.get("has_e2e_tests", False)
        self._add_check(
            "Testing",
            "E2E Tests",
            "End-to-end tests for critical flows",
            CheckStatus.PASS if has_e2e_tests else CheckStatus.WARNING,
            auto_fixable=True
        )
    
    def _check_observability(self, context: Dict) -> None:
        """Check monitoring and logging."""
        log.debug("   Checking observability...")
        
        # Logging
        has_logging = context.get("has_logging", False)
        self._add_check(
            "Observability",
            "Logging",
            "Comprehensive logging implemented",
            CheckStatus.PASS if has_logging else CheckStatus.FAIL,
            auto_fixable=True
        )
        
        # Health checks
        has_health_checks = context.get("has_health_check_endpoints", False)
        self._add_check(
            "Observability",
            "Health Checks",
            "Health check endpoints available",
            CheckStatus.PASS if has_health_checks else CheckStatus.FAIL,
            "/health or /readyz endpoints",
            auto_fixable=True
        )
        
        # Error tracking
        has_error_tracking = context.get("has_error_tracking", False)
        self._add_check(
            "Observability",
            "Error Tracking",
            "Error tracking configured (Sentry, etc.)",
            CheckStatus.PASS if has_error_tracking else CheckStatus.WARNING,
            "Sentry/Datadog" if has_error_tracking else "Not configured"
        )
        
        # Metrics
        has_metrics = context.get("has_metrics", False)
        self._add_check(
            "Observability",
            "Metrics",
            "Performance metrics collection",
            CheckStatus.PASS if has_metrics else CheckStatus.WARNING,
            "Prometheus/Grafana" if has_metrics else "Not configured"
        )
    
    def _check_deployment(self, context: Dict) -> None:
        """Check deployment readiness."""
        log.debug("   Checking deployment...")
        
        # Docker
        has_dockerfile = context.get("has_dockerfile", False)
        if has_dockerfile:
            self.artifacts_generated.append("Dockerfile")
        
        self._add_check(
            "Deployment",
            "Containerization",
            "Docker containerization",
            CheckStatus.PASS if has_dockerfile else CheckStatus.WARNING,
            auto_fixable=True
        )
        
        # CI/CD
        has_cicd = context.get("has_cicd_pipeline", False)
        self._add_check(
            "Deployment",
            "CI/CD Pipeline",
            "Automated build/test/deploy pipeline",
            CheckStatus.PASS if has_cicd else CheckStatus.WARNING,
            "GitHub Actions/GitLab CI" if has_cicd else "Manual deployment",
            auto_fixable=True
        )
        
        # Environment config
        has_env_config = context.get("has_environment_config", False)
        self._add_check(
            "Deployment",
            "Environment Configuration",
            "Separate configs for dev/staging/prod",
            CheckStatus.PASS if has_env_config else CheckStatus.FAIL
        )
        
        # Rollback plan
        has_rollback = context.get("has_rollback_plan", False)
        self._add_check(
            "Deployment",
            "Rollback Strategy",
            "Rollback procedure documented and tested",
            CheckStatus.PASS if has_rollback else CheckStatus.WARNING
        )
    
    def _check_documentation(self, context: Dict) -> None:
        """Check documentation completeness."""
        log.debug("   Checking documentation...")
        
        # README
        has_readme = context.get("has_readme", False)
        self._add_check(
            "Documentation",
            "README",
            "Comprehensive README with quickstart",
            CheckStatus.PASS if has_readme else CheckStatus.FAIL,
            auto_fixable=True
        )
        
        # API docs
        has_api_docs = context.get("has_api_documentation", False)
        self._add_check(
            "Documentation",
            "API Documentation",
            "API endpoint documentation",
            CheckStatus.PASS if has_api_docs else CheckStatus.WARNING,
            "OpenAPI/Swagger" if has_api_docs else "Missing",
            auto_fixable=True
        )
        
        # Architecture docs
        has_architecture_docs = context.get("has_architecture_documentation", False)
        self._add_check(
            "Documentation",
            "Architecture Docs",
            "System design documentation",
            CheckStatus.PASS if has_architecture_docs else CheckStatus.WARNING,
            auto_fixable=True
        )
        
        # Code comments
        has_code_comments = context.get("has_code_comments", False)
        self._add_check(
            "Documentation",
            "Code Comments",
            "Inline code documentation",
            CheckStatus.PASS if has_code_comments else CheckStatus.WARNING
        )
    
    def _check_compliance(self, context: Dict) -> None:
        """Check compliance requirements."""
        log.debug("   Checking compliance...")
        
        # GDPR (if applicable)
        if context.get("handles_personal_data", False):
            has_gdpr = context.get("gdpr_compliant", False)
            self._add_check(
                "Compliance",
                "GDPR",
                "GDPR compliance for EU user data",
                CheckStatus.PASS if has_gdpr else CheckStatus.FAIL,
                "Privacy policy, data deletion" if has_gdpr else "Not compliant"
            )
        
        # Accessibility
        if context.get("is_web_app", False):
            has_accessibility = context.get("wcag_compliant", False)
            self._add_check(
                "Compliance",
                "Accessibility",
                "WCAG 2.1 accessibility standards",
                CheckStatus.PASS if has_accessibility else CheckStatus.WARNING,
                "Screen reader support" if has_accessibility else "Not tested"
            )
    
    def _generate_recommendations(self) -> List[str]:
        """Generate prioritized recommendations based on failures."""
        recommendations = []
        
        # Critical failures first
        critical_items = [item for item in self.checklist 
                         if item.status == CheckStatus.FAIL]
        
        for item in critical_items:
            recommendations.append(
                f"🔴 CRITICAL: Fix {item.name} - {item.description}"
            )
        
        # Then warnings
        warning_items = [item for item in self.checklist 
                        if item.status == CheckStatus.WARNING]
        
        for item in warning_items[:5]:  # Top 5 warnings
            recommendations.append(
                f"🟡 IMPORTANT: Address {item.name} - {item.details or item.description}"
            )
        
        return recommendations
    
    def generate_deployment_artifacts(self, context: Dict) -> List[str]:
        """
        Generate Infrastructure as Code artifacts.
        
        Returns:
            List of generated artifact filenames
        """
        log.info("🏗️  Generating deployment artifacts...")
        
        artifacts = []
        
        # Generate Dockerfile
        dockerfile = self._generate_dockerfile(context)
        if dockerfile:
            artifacts.append("Dockerfile")
        
        # Generate docker-compose.yml
        compose = self._generate_docker_compose(context)
        if compose:
            artifacts.append("docker-compose.yml")
        
        # Generate GitHub Actions workflow
        workflow = self._generate_github_actions(context)
        if workflow:
            artifacts.append(".github/workflows/ci-cd.yml")
        
        # Generate Kubernetes manifests
        k8s = self._generate_kubernetes_manifests(context)
        if k8s:
            artifacts.append("k8s/deployment.yaml")
        
        self.artifacts_generated.extend(artifacts)
        log.info(f"   ✅ Generated {len(artifacts)} deployment artifacts")
        
        return artifacts
    
    def _generate_dockerfile(self, context: Dict) -> str:
        """Generate multi-stage Dockerfile."""
        language = context.get("language", "python")
        
        if language == "python":
            return '''# Multi-stage Dockerfile for production
FROM python:3.11-slim as builder

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Copy from builder
COPY --from=builder /root/.local /root/.local
COPY . .

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \\
    CMD python -c "import requests; requests.get('http://localhost:8000/health')"

# Run
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
'''
        return ""
    
    def _generate_docker_compose(self, context: Dict) -> str:
        """Generate docker-compose.yml for local development."""
        return '''version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:password@db:5432/app
      - REDIS_URL=redis://redis:6379
    depends_on:
      - db
      - redis
    volumes:
      - .:/app
    networks:
      - app-network

  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: app
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - app-network

  redis:
    image: redis:7-alpine
    networks:
      - app-network

networks:
  app-network:
    driver: bridge

volumes:
  postgres-data:
'''
    
    def _generate_github_actions(self, context: Dict) -> str:
        """Generate CI/CD workflow."""
        return '''name: CI/CD Pipeline

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
    - uses: actions/checkout@v4
    
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install pytest pytest-cov pylint
    
    - name: Lint
      run: |
        pylint src/ --fail-under=8.0
    
    - name: Test with coverage
      run: |
        pytest --cov=src --cov-report=xml
    
    - name: Upload coverage
      uses: codecov/codecov-action@v3

  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Deploy to production
      run: |
        echo "Deploying to production..."
        # Add deployment commands here
'''
    
    def _generate_kubernetes_manifests(self, context: Dict) -> str:
        """Generate K8s deployment manifest."""
        return '''apiVersion: apps/v1
kind: Deployment
metadata:
  name: app-deployment
spec:
  replicas: 3
  selector:
    matchLabels:
      app: myapp
  template:
    metadata:
      labels:
        app: myapp
    spec:
      containers:
      - name: app
        image: myapp:latest
        ports:
        - containerPort: 8000
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: app-service
spec:
  selector:
    app: myapp
  ports:
    - protocol: TCP
      port: 80
      targetPort: 8000
  type: LoadBalancer
'''


def assess_production_readiness(project_context: Dict) -> ProductionReadinessReport:
    """Convenience function for readiness assessment."""
    checker = ProductionReadinessChecker()
    return checker.assess_readiness(project_context)


def generate_deployment_artifacts(project_context: Dict) -> List[str]:
    """Convenience function for artifact generation."""
    checker = ProductionReadinessChecker()
    return checker.generate_deployment_artifacts(project_context)
