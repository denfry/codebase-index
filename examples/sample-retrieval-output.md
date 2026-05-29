# Sample Retrieval Output

Example output from `codebase-index search` after indexing a web application.

## Query: "where is user authentication implemented?"

### Command

```bash
codebase-index search "user authentication" --json
```

### Response

```json
{
  "query": "user authentication",
  "intent": "location",
  "confidence": "high",
  "index": {
    "exists": true,
    "stale": false,
    "files_changed_since_build": 0,
    "built_at": "2026-05-29T08:00:00Z",
    "head_commit": "abc1234"
  },
  "results": [
    {
      "rank": 1,
      "path": "src/auth/AuthService.ts",
      "line_start": 12,
      "line_end": 148,
      "symbols": ["AuthService", "login", "validatePassword", "logout"],
      "score": 0.92,
      "reason": "exact symbol match · AuthService class with login()",
      "snippet": "export class AuthService {\n  async login(username: string, password: string): Promise<Session> {\n    const user = await this.findUser(username);\n    if (!user || !this.validatePassword(password, user.hash)) {\n      throw new AuthenticationError('Invalid credentials');\n    }\n    return this.createSession(user);\n  }\n}"
    },
    {
      "rank": 2,
      "path": "src/routes/auth.ts",
      "line_start": 20,
      "line_end": 91,
      "symbols": ["loginHandler", "logoutHandler", "refreshTokenHandler"],
      "score": 0.78,
      "reason": "FTS match · 4 callers of AuthService.login()",
      "snippet": "router.post('/login', async (req, res) => {\n  const { username, password } = req.body;\n  const session = await authService.login(username, password);\n  res.cookie('session', session.token, { httpOnly: true });\n  res.json({ user: session.user });\n});"
    },
    {
      "rank": 3,
      "path": "src/middleware/auth.ts",
      "line_start": 5,
      "line_end": 42,
      "symbols": ["requireAuth", "optionalAuth"],
      "score": 0.65,
      "reason": "path match · FTS match · authentication middleware",
      "snippet": "export const requireAuth = async (req: Request, res: Response, next: NextFunction) => {\n  const token = req.cookies.session;\n  if (!token) return res.status(401).json({ error: 'Unauthorized' });\n  const session = await authService.validateSession(token);\n  if (!session) return res.status(401).json({ error: 'Invalid session' });\n  req.user = session.user;\n  next();\n};"
    }
  ],
  "recommended_reads": [
    { "path": "src/auth/AuthService.ts", "line_start": 12, "line_end": 148 },
    { "path": "src/routes/auth.ts", "line_start": 20, "line_end": 91 },
    { "path": "src/middleware/auth.ts", "line_start": 5, "line_end": 42 }
  ],
  "fallback_suggestions": {
    "ripgrep": ["AuthService", "login.*password", "authentication", "authenticate"],
    "likely_paths": ["src/auth/", "src/middleware/", "src/routes/auth.ts"]
  }
}
```

### Human-Readable Output

```bash
codebase-index search "user authentication"
```

```
Top matches:
┌──────┬──────────────────────────┬──────────────────────────────┬───────┬──────────────────────────────────┐
│ Rank │ Path                     │ Symbols                      │ Score │ Reason                           │
├──────┼──────────────────────────┼──────────────────────────────┼───────┼──────────────────────────────────┤
│    1 │ src/auth/AuthService.ts  │ AuthService, login, logout   │  0.92 │ exact symbol match               │
│    2 │ src/routes/auth.ts       │ loginHandler, logoutHandler  │  0.78 │ FTS match · 4 callers            │
│    3 │ src/middleware/auth.ts   │ requireAuth, optionalAuth    │  0.65 │ path match · FTS match           │
└──────┴──────────────────────────┴──────────────────────────────┴───────┴──────────────────────────────────┘

Recommended reads:
  1. src/auth/AuthService.ts:12-148
  2. src/routes/auth.ts:20-91
  3. src/middleware/auth.ts:5-42
```

## Query: "what breaks if I change the User model?"

### Command

```bash
codebase-index impact "User" --json
```

### Response (abbreviated)

```json
{
  "query": "User",
  "intent": "impact",
  "confidence": "high",
  "results": [
    {
      "rank": 1,
      "path": "src/models/user.py",
      "symbols": ["User"],
      "score": 1.0,
      "reason": "symbol definition · 12 dependents",
      "snippet": "class User(BaseModel): ..."
    },
    {
      "rank": 2,
      "path": "src/auth/AuthService.ts",
      "symbols": ["findUser", "createUser"],
      "score": 0.85,
      "reason": "direct reference · imports User",
      "snippet": "import { User } from '../models/user';"
    },
    {
      "rank": 3,
      "path": "src/routes/users.ts",
      "symbols": ["getUserHandler", "updateUserHandler"],
      "score": 0.72,
      "reason": "direct reference · 2 callers",
      "snippet": "const user: User = await userService.findById(id);"
    }
  ],
  "impact_summary": {
    "total_affected_files": 8,
    "total_affected_symbols": 15,
    "max_depth": 3
  }
}
```
