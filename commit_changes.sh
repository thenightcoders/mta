#!/bin/bash

# Smart commit script for incremental commits
# Usage: ./commit_changes.sh

set -e  # Exit on any error

echo "🚀 Starting incremental commits..."

# Function to commit with message and optional files
commit_files() {
    local message="$1"
    shift
    local files=("$@")
    
    echo "📝 Committing: $message"
    git add "${files[@]}"
    git commit -m "$message"
    echo "✅ Committed: $message"
    echo ""
}

# Check if we're in a git repo
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "❌ Not in a git repository"
    exit 1
fi

# Check if there are changes to commit
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
    echo "ℹ️  No changes to commit"
    exit 0
fi

echo "📋 Files with changes:"
git status --porcelain
echo ""

# First, unstage any staged files so we can commit them in logical groups
if ! git diff --cached --quiet; then
    echo "🔄 Unstaging previously staged files for logical grouping..."
    git restore --staged .
    echo ""
fi

# 1. New service architecture (most important first)
echo "🏗️  Committing new service architecture..."
if [ -d "email_service" ]; then
    commit_files "🏗️ Add email service: comprehensive email handling with Django Q integration" \
        email_service/
fi

if [ -f "users/services.py" ]; then
    commit_files "🏗️ Add user services: extract business logic from views to service layer" \
        users/services.py
fi

if [ -f "users/utils.py" ]; then
    commit_files "🏗️ Add user utilities: helper functions for user management operations" \
        users/utils.py
fi

# 2. Database migrations
if ls transfers/migrations/*.py > /dev/null 2>&1; then
    migration_files=($(ls transfers/migrations/*.py 2>/dev/null | grep -v __pycache__ | head -5))
    if [ ${#migration_files[@]} -gt 0 ]; then
        commit_files "🗃️ Add transfer migrations: update commission config constraints" \
            "${migration_files[@]}"
    fi
fi

# 3. Settings and configuration
if git diff --name-only | grep -E "(config/settings\.py|\.env|\.gitignore)" > /dev/null 2>&1; then
    echo "⚙️  Committing settings and configuration..."
    settings_files=()
    if git diff --name-only | grep "config/settings.py" > /dev/null 2>&1; then
        settings_files+=("config/settings.py")
    fi
    if git diff --name-only | grep ".gitignore" > /dev/null 2>&1; then
        settings_files+=(".gitignore")
    fi
    if [ ${#settings_files[@]} -gt 0 ]; then
        commit_files "⚙️ Improve settings: production-ready config with Q cluster and conditional email TLS" \
            "${settings_files[@]}"
    fi
fi

# 4. User models improvements
if git diff --name-only | grep "users/models\.py" > /dev/null 2>&1; then
    echo "👤 Committing user model improvements..."
    commit_files "👤 Enhance user models: improve activity logging and add cleanup utilities" \
        users/models.py
fi

# 5. User signals and middleware
if git diff --name-only | grep "users/signals\.py" > /dev/null 2>&1; then
    echo "🔄 Committing signal improvements..."
    commit_files "🔄 Improve audit signals: better error handling and financial compliance tracking" \
        users/signals.py
fi

# 6. User views refactoring
if git diff --name-only | grep "users/views\.py" > /dev/null 2>&1; then
    echo "🎯 Committing user views refactoring..."
    commit_files "🎯 Refactor user views: extract business logic to services for better separation" \
        users/views.py
fi

# 7. Navigation improvements
if git diff --name-only | grep "templates/base\.html" > /dev/null 2>&1; then
    echo "🧭 Committing navigation improvements..."
    commit_files "🧭 Reorganize navigation: logical menu grouping and proper superuser badge styling" \
        templates/base.html
fi

# 8. Profile page improvements
if git diff --name-only | grep "templates/users/profile\.html" > /dev/null 2>&1; then
    echo "✨ Committing profile page improvements..."
    commit_files "✨ Enhance profile page: clear visual indicators for editable vs readonly fields" \
        templates/users/profile.html
fi

# 9. Manager dashboard improvements
if git diff --name-only | grep "templates/users/manager_dashboard\.html" > /dev/null 2>&1; then
    echo "📊 Committing dashboard improvements..."
    commit_files "📊 Clean up manager dashboard: remove redundant superuser badges and improve text" \
        templates/users/manager_dashboard.html
fi

# 10. French translation updates (commission templates)
if git diff --name-only | grep -E "templates/transfers/.*\.html" > /dev/null 2>&1; then
    echo "🇫🇷 Committing French translation updates..."
    commission_files=($(git diff --name-only | grep "templates/transfers/.*\.html"))
    if [ ${#commission_files[@]} -gt 0 ]; then
        commit_files "🇫🇷 Update French translations: 'gestionnaire' → 'manager' in commission templates" \
            "${commission_files[@]}"
    fi
fi

# 11. Remove unused files (handle deletions)
if git status --porcelain | grep "^.D" > /dev/null 2>&1; then
    echo "🗑️  Committing file deletions..."
    # Add deleted files to staging
    git add -u
    git commit -m "🗑️ Remove unused files: cleanup obsolete utility files"
    echo "✅ Committed: 🗑️ Remove unused files: cleanup obsolete utility files"
    echo ""
fi

# 12. Any remaining untracked files
untracked_files=($(git ls-files --others --exclude-standard | grep -v "diff.txt"))
if [ ${#untracked_files[@]} -gt 0 ]; then
    echo "📦 Committing remaining untracked files..."
    commit_files "📦 Add miscellaneous files: additional utilities and documentation" \
        "${untracked_files[@]}"
fi

# 13. Any remaining modified files (catch-all)
remaining_files=($(git diff --name-only | grep -v "diff.txt"))
if [ ${#remaining_files[@]} -gt 0 ]; then
    echo "📦 Committing remaining changes..."
    commit_files "📦 Misc improvements: various small enhancements and fixes" \
        "${remaining_files[@]}"
fi

echo "🎉 All changes committed successfully!"
echo ""
echo "📈 Recent commits:"
git log --oneline -10
