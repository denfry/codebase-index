# Demo Project

This is a sample project structure for demonstrating `codebase-index` capabilities.

## Structure

```
demo-project/
├── src/
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── service.py        # AuthService class
│   │   └── middleware.py     # requireAuth middleware
│   ├── models/
│   │   ├── __init__.py
│   │   └── user.py           # User model
│   ├── routes/
│   │   ├── __init__.py
│   │   └── auth.py           # Login/logout routes
│   ├── config.py             # Configuration loader
│   └── app.py                # Application entry point
├── tests/
│   ├── test_auth.py
│   └── test_user.py
├── .env                      # Should be excluded from index
├── .gitignore
└── package.json
```

## Try It

```bash
cd examples/demo-project

# Initialize and index
codebase-index init
codebase-index index

# Try some queries
codebase-index search "authentication"
codebase-index symbol "AuthService"
codebase-index refs "login"
codebase-index impact "User"
codebase-index stats
```

## Expected Results

After indexing, you should see:

- `AuthService` class extracted from `src/auth/service.py`
- `User` model extracted from `src/models/user.py`
- Route handlers extracted from `src/routes/auth.py`
- `.env` file excluded (secret file)
- FTS5 index populated with chunk text from all source files
