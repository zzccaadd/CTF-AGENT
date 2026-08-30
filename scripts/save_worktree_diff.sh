#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

output_dir="$repo_root/.codex-diffs"
mkdir -p "$output_dir"

timestamp="$(date +%Y%m%d-%H%M%S-%N)"
output_file="$output_dir/worktree-$timestamp.diff"

{
    printf '# Worktree diff snapshot generated at %s\n' "$(date --iso-8601=seconds)"
    printf '# Includes tracked changes and non-ignored untracked files.\n\n'
    git diff --binary

    while IFS= read -r -d '' file; do
        git diff --no-index --binary /dev/null "$file" || true
    done < <(git ls-files --others --exclude-standard -z)
} > "$output_file"

printf '%s\n' "$output_file"
