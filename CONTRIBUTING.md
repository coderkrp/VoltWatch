# Contributing to VoltWatch

First off, thank you for considering contributing to VoltWatch! It's people like you that make VoltWatch a great tool.

## Development Setup

1. **Fork** the repo on GitHub.
2. **Clone** the project to your own machine.
3. **Set up** the Python environments for both the backend and dashboard using `pip install -r requirements.txt`.
4. Install the **pre-commit hooks**:
   ```bash
   pip install pre-commit
   pre-commit install
   ```

## Pull Request Process

1. Ensure any install or build dependencies are removed before the end of the layer when doing a build.
2. Update the README.md with details of changes to the interface, this includes new environment variables, exposed ports, useful file locations, and container parameters.
3. Ensure all tests pass. We enforce 100% test passing on our CI pipeline.
4. Run `ruff check .` and `black .` locally before pushing.
5. You may merge the Pull Request in once you have the sign-off of the core maintainers, or if you do not have permission to do that, you may request the reviewer to merge it for you.

## Architecture Guidelines
When proposing new features, please adhere to our philosophy outlined in `ARCHITECTURE.md`:
- Prefer clean modularity over unnecessary abstractions.
- No "fake enterprise complexity" (e.g., don't add Redis unless it solves an actual bottleneck).
- Keep it Solo-Developer Friendly.

Thank you!
