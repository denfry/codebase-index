# VHS tape for the README demo (see docs/DEMO.md). Run from the repository root
# after cloning Flask into .tmp-demo/flask at the pinned commit:
#   vhs docs/demo.tape
Output assets/demo.gif
Set FontSize 15
Set Width 1200
Set Height 720
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

Type "cd .tmp-demo/flask && codebase-index index"
Enter
Sleep 4s

Type 'codebase-index search "where is the session cookie signed and saved" --limit 3'
Enter
Sleep 5s

Type "codebase-index refs open_session"
Enter
Sleep 4s

Type "codebase-index impact SecureCookieSessionInterface --direction up --depth 2"
Enter
Sleep 5s

Type "codebase-index diff-impact"
Enter
Sleep 6s
