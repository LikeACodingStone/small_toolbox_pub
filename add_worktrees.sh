#!/usr/bin/env bash
# Create and update worktrees for local branches and origin branches.
# Example: Audio01_AudioFilterTools -> .worktrees/Audio01
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./add_worktrees.sh [--dry-run]

Fetch origin, then add or update worktrees for all branches.
Folder names use the branch name before the first underscore; slashes
are replaced with hyphens. Skip main and master. Existing worktrees are
updated in their current locations. Only clean worktrees are fast-forwarded
to the matching origin branch. Local commits are never discarded.

  --dry-run   Preview using cached remote refs, without fetching or changing files.
  -h, --help  Show this help.

Branches with no matching origin branch are kept as local branches.
EOF
}

dry_run=false
case "${1:-}" in
    --dry-run) dry_run=true ;;
    -h|--help) usage; exit 0 ;;
    '') ;;
    *) usage >&2; exit 2 ;;
esac
if (( $# > 1 )); then
    usage >&2
    exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(git -C "$script_dir" rev-parse --show-toplevel)"
cd -- "$repo_root"

if [[ $dry_run == false ]]; then
    git fetch origin
else
    printf 'Dry run: using cached origin refs; a normal run fetches first.\n'
fi

declare -A checked_out=() destinations=()
worktree_path=''
while IFS= read -r -d '' line; do
    if [[ $line == 'worktree '* ]]; then
        worktree_path="${line#worktree }"
    fi
    if [[ $line == 'branch refs/heads/'* ]]; then
        checked_out["${line#branch refs/heads/}"]="$worktree_path"
    fi
done < <(git worktree list --porcelain -z)

mapfile -t branches < <(
    git for-each-ref --format='%(refname)' refs/heads/ refs/remotes/origin/ |
        sed -e 's@^refs/heads/@@' -e 's@^refs/remotes/origin/@@' |
        LC_ALL=C sort -u
)

declare -a planned_branches=() planned_paths=()
errors=0
for branch in "${branches[@]}"; do
    case "$branch" in main|master|HEAD) continue ;; esac
    if [[ ${checked_out[$branch]+yes} ]]; then
        planned_branches+=("$branch")
        planned_paths+=("${checked_out[$branch]}")
        continue
    fi
    folder="${branch%%_*}"
    folder="${folder//\//-}"
    if [[ -z $folder || $folder == . || $folder == .. ]]; then
        printf 'Invalid folder prefix for branch: %s\n' "$branch" >&2
        errors=1
        continue
    fi
    path=".worktrees/$folder"
    if [[ -e $path || -L $path ]]; then
        printf 'Cannot add %s: %s already exists.\n' "$branch" "$path" >&2
        errors=1
        continue
    fi
    if [[ ${destinations[$path]+yes} ]]; then
        printf 'Folder collision: %s and %s both use %s.\n' \
            "${destinations[$path]}" "$branch" "$path" >&2
        errors=1
        continue
    fi
    destinations[$path]="$branch"
    planned_branches+=("$branch")
    planned_paths+=("$path")
done

# Validate all destinations before creating any worktrees.
if (( errors )); then
    exit 1
fi
for i in "${!planned_branches[@]}"; do
    branch="${planned_branches[$i]}"
    path="${planned_paths[$i]}"
    if [[ ${checked_out[$branch]+yes} ]]; then
        command=()
    elif git show-ref --verify --quiet "refs/heads/$branch"; then
        command=(git worktree add "$path" "$branch")
    else
        command=(git worktree add --track -b "$branch" "$path" "origin/$branch")
    fi
    if (( ${#command[@]} )); then
        printf '%q ' "${command[@]}"
        printf '\n'
        if [[ $dry_run == false ]]; then
            mkdir -p -- .worktrees
            "${command[@]}"
        fi
    fi

    remote_ref="refs/remotes/origin/$branch"
    if ! git show-ref --verify --quiet "$remote_ref"; then
        printf 'Keep %s (no matching origin branch)\n' "$branch"
        continue
    fi
    if [[ -d $path ]] && [[ -n $(git -C "$path" status --porcelain --untracked-files=all) ]]; then
        printf 'Skip update of %s (local changes)\n' "$branch" >&2
        errors=1
        continue
    fi
    if ! git show-ref --verify --quiet "refs/heads/$branch"; then
        # A new remote branch in dry-run mode has not been created yet.
        continue
    fi
    local_tip="$(git rev-parse "refs/heads/$branch")"
    remote_tip="$(git rev-parse "$remote_ref")"
    if [[ $local_tip == "$remote_tip" ]]; then
        printf 'Up to date: %s\n' "$branch"
    elif git merge-base --is-ancestor "$local_tip" "$remote_tip"; then
        command=(git -C "$path" merge --ff-only "$remote_ref")
        printf '%q ' "${command[@]}"
        printf '\n'
        if [[ $dry_run == false ]]; then
            if ! "${command[@]}"; then
                errors=1
            fi
        fi
    elif git merge-base --is-ancestor "$remote_tip" "$local_tip"; then
        printf 'Keep %s (local commits ahead of origin)\n' "$branch"
    else
        printf 'Skip update of %s (local and origin history diverged)\n' "$branch" >&2
        errors=1
    fi
done
if (( ${#planned_branches[@]} == 0 )); then
    printf 'No new worktrees to add.\n'
fi
exit "$errors"
