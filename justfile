# Run the test suite
test:
    python -m pytest

# Run lint checks
lint:
    ruff check .

# Format the codebase
format:
    ruff format .

# Check formatting without modifying files
fmt-check:
    ruff format --check .

# Run type checks
typecheck:
    pyright

# Fast static checks for the pre-commit hook (no type check, no tests)
check-fast: lint fmt-check

# Run the standard local verification set (also runs in the pre-push hook)
check: check-fast typecheck test

# List open issues with hierarchy and priority
list-open:
    ./scripts/list_open_issues.py

# Install pre-commit (fast checks) and pre-push (full check) git hooks
install-hooks:
    #!/usr/bin/env sh
    install_hook() {
        name="$1"
        cmd="$2"
        path=".git/hooks/$name"
        if [ -f "$path" ]; then
            echo "A $name hook already exists at $path."
            echo "To use RAVEN's gate, add this line to it:"
            printf "  %s\n" "$cmd"
        else
            mkdir -p .git/hooks
            printf '#!/bin/sh\n%s\n' "$cmd" > "$path"
            chmod +x "$path"
            echo "Installed $path to run '$cmd'."
        fi
    }
    install_hook pre-commit "just check-fast"
    install_hook pre-push "just check"
