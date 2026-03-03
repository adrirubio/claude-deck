# Contributing

Thanks for your interest in contributing to Claude Deck! We welcome pull requests and issues from everyone.

## Getting Started

1. Fork the repo and clone it:

```bash
git clone https://github.com/<your-username>/claude-deck.git
cd claude-deck
```

2. Run the install script (requires Python 3.11+ and Node.js 18+):

```bash
./scripts/install.sh
```

3. Start the dev servers:

```bash
./scripts/dev.sh
```

Backend runs at `http://localhost:8000`, frontend at `http://localhost:5173`.

## Code Style

### Frontend

- TypeScript strict mode (`noUnusedLocals`, `noUnusedParameters`)
- ESLint — run `cd frontend && npm run lint` before submitting
- Tailwind CSS + shadcn/ui for styling
- Path alias `@/*` maps to `./src/*`

### Backend

- Python with type hints throughout
- Async/await patterns
- Pydantic models for request/response validation

## Project Structure

Each feature lives in its own module under `frontend/src/features/`. When adding a new feature:

1. Create a directory in `frontend/src/features/<name>/`
2. Add a page component, sub-components, API functions, and types
3. Register the route in `frontend/src/App.tsx`
4. Add the backend route module in `backend/app/api/v1/`
5. Register the router in `backend/app/api/v1/router.py`

## Submitting Changes

1. Create a branch for your change
2. Make your changes and test them locally
3. Run `cd frontend && npm run lint` to check for lint errors
4. Open a pull request with a clear description of what you changed and why

## Reporting Issues

Found a bug or have a feature idea? [Open an issue](https://github.com/adrirubio/claude-deck/issues) and include:

- What you expected to happen
- What actually happened
- Steps to reproduce (if applicable)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
