# Run the test suite
test:
    python -m pytest

# Run lint checks
lint:
    ruff check .

# Format the codebase
format:
    ruff format .

# Run type checks
typecheck:
    pyright

# Run the standard local verification set
check: lint typecheck test

# List open issues with hierarchy and priority
list-open:
    ./scripts/list_open_issues.py

# Install a pre-commit git hook that runs 'just check'
install-hooks:
    #!/usr/bin/env sh
    if [ -f .git/hooks/pre-commit ]; then
        echo "A pre-commit hook already exists at .git/hooks/pre-commit."
        echo "To use RAVEN's check, add this line to it:"
        printf "  just check\n"
    else
        mkdir -p .git/hooks
        printf '#!/bin/sh\njust check\n' > .git/hooks/pre-commit
        chmod +x .git/hooks/pre-commit
        echo "Installed .git/hooks/pre-commit to run 'just check' before each commit."
    fi
