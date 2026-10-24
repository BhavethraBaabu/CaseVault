#!/usr/bin/env bash
set -euo pipefail
REPO="BhavethraBaabu/CaseVault"
COAUTHOR=""   # e.g. "Friend Name <12345+friend@users.noreply.github.com>" — leave empty to skip Pair Extraordinaire

WORK="$(mktemp -d)"
gh repo clone "$REPO" "$WORK/CaseVault"
cd "$WORK/CaseVault"
DEF=$(gh repo view "$REPO" --json defaultBranchRef -q .defaultBranchRef.name)

pr() {  # branch, title, commit-msg-extra
  git push -u origin "$1"
  gh pr create -t "$2" -b "$2" -B "$DEF" -H "$1"
  gh pr merge "$1" --squash --delete-branch
  git checkout "$DEF" && git pull --ff-only
}

# 1) Quickdraw: open + close an issue within seconds
URL=$(gh issue create -R "$REPO" -t "Add contributor docs" -b "Tracking repo hygiene files.")
gh issue close "$URL" -c "Handled via PRs."

# 2) YOLO + Pull Shark #1: CONTRIBUTING.md, merged without review
git checkout -b docs/contributing
cat > CONTRIBUTING.md << 'MD'
# Contributing to CaseVault

1. Fork the repo and create a branch: `git checkout -b feature/your-change`
2. Keep commits small and descriptive.
3. Open a pull request against the default branch with a clear summary.
4. Make sure the project builds and tests pass before requesting review.
MD
git add CONTRIBUTING.md && git commit -m "docs: add CONTRIBUTING.md"
pr docs/contributing "docs: add CONTRIBUTING.md"

# 3) Pull Shark #2: .editorconfig
git checkout -b chore/editorconfig
cat > .editorconfig << 'CFG'
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 2

[*.{java,py}]
indent_size = 4

[*.md]
trim_trailing_whitespace = false
CFG
git add .editorconfig && git commit -m "chore: add .editorconfig"
pr chore/editorconfig "chore: add .editorconfig"

# 4) Pair Extraordinaire: co-authored commit (only if COAUTHOR set)
if [ -n "$COAUTHOR" ]; then
  git checkout -b docs/security
  cat > SECURITY.md << 'MD'
# Security Policy

Please report vulnerabilities privately via GitHub Security Advisories
(Security tab -> "Report a vulnerability") rather than opening a public issue.
MD
  git add SECURITY.md
  git commit -m "docs: add SECURITY.md" -m "Co-authored-by: $COAUTHOR"
  pr docs/security "docs: add SECURITY.md"
fi

echo "Done. Check https://github.com/BhavethraBaabu?tab=achievements in a few hours."
