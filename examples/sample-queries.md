# Sample Queries

Natural language questions mapped to `codebase-index` CLI commands.

## Finding Implementation

| Question | Command |
|---|---|
| Where is authentication implemented? | `codebase-index search "authentication"` |
| Find the user model | `codebase-index symbol "User"` |
| Where is the database connection configured? | `codebase-index search "database connection config"` |
| Locate the API router | `codebase-index search "API router"` |
| Where are environment variables loaded? | `codebase-index search "environment variables load"` |

## Understanding Code

| Question | Command |
|---|---|
| How does the login flow work? | `codebase-index search "login flow"` |
| Explain the request middleware | `codebase-index search "request middleware"` |
| How is data validated before saving? | `codebase-index search "data validation save"` |
| What does the build script do? | `codebase-index search "build script"` |
| Explain the error handling strategy | `codebase-index search "error handling"` |

## Finding References

| Question | Command |
|---|---|
| Who calls AuthService.login? | `codebase-index refs "AuthService.login"` |
| What imports the User model? | `codebase-index refs "User"` |
| Where is the config object used? | `codebase-index refs "config"` |
| Find all uses of the logger | `codebase-index refs "logger"` |

## Impact Analysis

| Question | Command |
|---|---|
| What breaks if I change the User model? | `codebase-index impact "User"` |
| What depends on the auth middleware? | `codebase-index impact "auth middleware"` |
| Impact of removing the cache layer | `codebase-index impact "cache"` |
| What files call the API client? | `codebase-index impact "apiClient"` |

## Architecture Overview

| Question | Command |
|---|---|
| What is the project structure? | `codebase-index search "project structure architecture"` |
| Where is the main entry point? | `codebase-index search "main entry point"` |
| What are the core modules? | `codebase-index search "core modules"` |
| How is the app initialized? | `codebase-index search "app initialization bootstrap"` |

## Debugging

| Question | Command |
|---|---|
| Why am I getting a 401 error? | `codebase-index search "401 unauthorized error"` |
| Where is this exception thrown? | `codebase-index search "AuthenticationError"` |
| What causes the timeout? | `codebase-index search "timeout"` |

## Symbol-Specific

| Question | Command |
|---|---|
| Show me the AuthService class | `codebase-index symbol "AuthService"` |
| Find the login function | `codebase-index symbol "login"` |
| Where is the Database class defined? | `codebase-index symbol "Database"` |
| Show all methods of UserService | `codebase-index symbol "UserService"` |
