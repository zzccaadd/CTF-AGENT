#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

output_dir="$repo_root/.codex-diffs"
mkdir -p "$output_dir"

timestamp="$(date +%Y%m%d-%H%M%S-%N)"
output_file="$output_dir/worktree-$timestamp.diff"
full_payload_file="$(mktemp "${TMPDIR:-/tmp}/codex-diff-full.XXXXXX")"
payload_file="$(mktemp "${TMPDIR:-/tmp}/codex-diff-delta.XXXXXX")"
previous_payload="$output_dir/.last-full-worktree.diff"
trap 'rm -f "$full_payload_file" "$payload_file"' EXIT

{
    # Exclude the snapshot directory from tracked changes as well as the
    # untracked-file scan below; historical snapshots must never nest.
    git diff --binary -- . ':(exclude).codex-diffs/**'

    while IFS= read -r -d '' file; do
        # The snapshot directory may intentionally be unignored. Never include
        # prior snapshots or the file currently being generated.
        case "$file" in
            .codex-diffs/*) continue ;;
        esac
        git diff --no-index --binary /dev/null "$file" || true
    done < <(git ls-files --others --exclude-standard -z)
} > "$full_payload_file"

if [[ -s "$previous_payload" ]]; then
    # Reconstruct both worktree states from their full payloads, then ask git
    # for the true source-level delta. Comparing patch text would retain
    # unchanged hunks and is the source of the old duplicate snapshots.
    old_tree="$(mktemp -d "${TMPDIR:-/tmp}/codex-diff-old.XXXXXX")"
    new_tree="$(mktemp -d "${TMPDIR:-/tmp}/codex-diff-new.XXXXXX")"
    git archive HEAD | tar -x -C "$old_tree"
    git archive HEAD | tar -x -C "$new_tree"
    (cd "$old_tree" && git apply "$previous_payload")
    (cd "$new_tree" && git apply "$full_payload_file")

    git -C "$old_tree" init -q
    git -C "$old_tree" config user.email codex-diff@invalid
    git -C "$old_tree" config user.name codex-diff
    git -C "$old_tree" add -A
    git -C "$old_tree" commit -qm "previous worktree state"
    rsync -a --delete --exclude .git "$new_tree"/ "$old_tree"/
    # Include both tracked changes and files newly added since the previous
    # baseline. `git diff` alone omits untracked files in the reconstructed tree.
    (
        cd "$old_tree"
        git diff --binary
        while IFS= read -r -d '' file; do
            git diff --no-index --binary /dev/null "$file" || true
        done < <(git ls-files --others --exclude-standard -z)
    ) > "$payload_file"
else
    cp "$full_payload_file" "$payload_file"
fi

# Persist the complete current state as the next invocation's baseline.
cp "$full_payload_file" "$previous_payload"

if [[ ! -s "$payload_file" ]]; then
    printf 'No worktree changes; no diff snapshot created.\n'
    exit 0
fi

# Repeated invocations before staging produce the same payload. Do not create
# another timestamped copy when the latest snapshot is byte-for-byte equivalent.
latest="$(find "$output_dir" -maxdepth 1 -type f -name '*.diff' -printf '%T@ %p\n' \
    | sort -nr | sed -n '1s/^[^ ]* //p')"
if [[ -n "$latest" ]] && tail -n +4 "$latest" | cmp -s - "$payload_file"; then
    printf '%s\n' "$latest"
    exit 0
fi

{
    printf '# Incremental worktree diff snapshot generated at %s\n' "$(date --iso-8601=seconds)"
    printf '# Contains only changes since the previous snapshot baseline.\n\n'
    cat "$payload_file"
} > "$output_file"

printf '%s\n' "$output_file"
