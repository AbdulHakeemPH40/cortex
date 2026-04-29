# 🔒 Security Guide - API Key Protection

## ⚠️ CRITICAL: Your API Keys Were Exposed!

Your `.env` file contained **real API keys** that were being tracked by Git. This has been fixed, but you should **rotate your API keys immediately** if this repository is public or shared.

---

## ✅ What Was Fixed

### **1. `.gitignore` Updated**
The `.gitignore` file now properly excludes:
- ✅ `.env` - Contains real API keys (NEVER commit)
- ✅ `.env.local`, `.env.production`, `.env.development` - Environment-specific keys
- ✅ `*.env` - Any file ending in `.env`

### **2. `.env` Removed from Git**
```bash
git rm --cached .env
```
This removes `.env` from Git tracking while keeping it on your local machine.

### **3. `.env.example` Preserved**
The `.env.example` file contains **only placeholders** and is safe to commit as a template.

---

## 🚨 IMMEDIATE ACTIONS REQUIRED

### **Step 1: Rotate Your API Keys**
Since your keys were in Git history, assume they are compromised. Generate new keys:

1. **Mistral API**: https://console.mistral.ai/api-keys
2. **DeepSeek API**: https://platform.deepseek.com/api_keys
3. **SiliconFlow API**: https://cloud.siliconflow.cn/

### **Step 2: Update Your `.env` File**
Replace old keys with new ones in your local `.env` file:

```env
# NEVER commit this file to Git!
MISTRAL_API_KEY=your-new-mistral-key
DEEPSEEK_API_KEY=your-new-deepseek-key
SILICONFLOW_API_KEY=your-new-siliconflow-key
```

### **Step 3: Clear Git History (Optional but Recommended)**
If your repository is public, consider:

```bash
# Remove .env from all Git history
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch .env' \
  --prune-empty --tag-name-filter cat -- --all

# Force push (WARNING: rewrites history)
git push origin --force --all
```

**Alternative**: Use [BFG Repo-Cleaner](https://rtyley.github.io/bfg-repo-cleaner/) (faster):
```bash
bfg --delete-files .env
git reflog expire --expire=now --all
git gc --prune=now --aggressive
git push --force
```

---

## 📋 Git Security Best Practices

### **✅ DO:**
- ✅ Use `.env.example` as a template with placeholder values
- ✅ Add `.env` to `.gitignore` immediately
- ✅ Use environment variables in production
- ✅ Rotate keys regularly (every 90 days)
- ✅ Use separate keys for development and production
- ✅ Audit Git history for accidentally committed secrets

### **❌ NEVER:**
- ❌ Commit `.env` files with real keys
- ❌ Hardcode API keys in source code
- ❌ Share API keys in commits, PRs, or issues
- ❌ Use production keys in development
- ❌ Store keys in client-side code (HTML/JS)

---

## 🔍 Verify Your Repository is Clean

### **Check if .env is tracked:**
```bash
git ls-files | grep ".env"
# Should return nothing (or only .env.example)
```

### **Check Git status:**
```bash
git status
# .env should appear in "Untracked files" or not at all
```

### **Search Git history for keys:**
```bash
# Search for known key patterns
git log -p --all -S "sk-" | grep -E "(sk-[a-f0-9]{32}|MISTRAL_API_KEY|DEEPSEEK_API_KEY)"

# Search for your old keys (replace with actual old key prefix)
git log -p --all -S "sk-712540f6ac904bed"
```

---

## 🛡️ Additional Security Measures

### **1. Use Pre-Commit Hooks**
Install [git-secrets](https://github.com/awslabs/git-secrets) to prevent committing secrets:

```bash
# Install git-secrets
git secrets --install

# Add patterns to detect
git secrets --add 'sk-[a-zA-Z0-9]{32,}'
git secrets --add 'API_KEY='
git secrets --add 'PASSWORD='

# Scan existing history
git secrets --scan
```

### **2. GitHub Secret Scanning**
If using GitHub:
- Enable [Secret Scanning](https://docs.github.com/en/code-security/secret-scanning)
- Set up [Push Protection](https://docs.github.com/en/code-security/secret-scanning/protecting-from-pushes)
- Review [Secret Alerts](https://docs.github.com/en/code-security/secret-scanning/managing-alerts-from-secret-scanning)

### **3. Use a Secrets Manager**
For production:
- **AWS**: AWS Secrets Manager
- **Azure**: Azure Key Vault
- **GCP**: Secret Manager
- **Open Source**: HashiCorp Vault

---

## 📄 Current `.gitignore` Protection

Your `.gitignore` now protects:

```gitignore
# SENSITIVE FILES - NEVER COMMIT TO GIT
.env
.env.local
.env.production
.env.development
*.env

# Python packages with potential keys
*.egg-info/

# IDE configs (may contain paths/keys)
.vscode/
.idea/
.qoder/
.cortex/

# Logs (may contain sensitive data)
*.log
logs/
```

---

## 🔄 Workflow for Team Members

### **First Time Setup:**
```bash
# 1. Clone repository
git clone <repo-url>

# 2. Copy example env file
cp .env.example .env

# 3. Edit .env with your own keys
nano .env  # or your preferred editor

# 4. .env is automatically ignored by Git
git status  # Verify .env is not tracked
```

### **Updating Dependencies:**
```bash
# If .env.example changes (new keys added)
git pull
cat .env.example  # Review new template
# Add any new keys to your local .env file
```

---

## 🚨 Emergency Response

### **If you accidentally commit a key:**

1. **Immediately rotate the key** at the provider's website
2. **Remove from Git history** (see Step 3 above)
3. **Force push** to update remote
4. **Notify team members** to update their `.env` files
5. **Check access logs** for unauthorized usage

### **Example commands:**
```bash
# 1. Rotate key at provider website first!

# 2. Remove from history
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch .env' \
  --prune-empty --tag-name-filter cat -- --all

# 3. Force push
git push origin --force --all

# 4. Notify team
echo "SECURITY: .env was committed. Keys rotated. Please pull latest changes." | \
  mail -s "Security Alert" team@company.com
```

---

## ✅ Verification Checklist

- [x] `.env` added to `.gitignore`
- [x] `.env` removed from Git tracking (`git rm --cached`)
- [x] `.env.example` contains only placeholders
- [ ] API keys rotated (if repository is public/shared)
- [ ] Git history cleared of old keys (if needed)
- [ ] Pre-commit hooks installed (recommended)
- [ ] Team members notified (if applicable)

---

## 📚 Additional Resources

- [GitHub - Keeping secrets safe](https://docs.github.com/en/code-security/getting-started/keeping-your-secrets-safe)
- [Git Secrets](https://github.com/awslabs/git-secrets)
- [BFG Repo-Cleaner](https://rtyley.github.io/bfg-repo-cleaner/)
- [12-Factor App - Config](https://12factor.net/config)

---

**Last Updated**: April 29, 2026  
**Status**: ✅ `.env` protection active  
**Action Required**: 🔴 Rotate exposed API keys immediately!
