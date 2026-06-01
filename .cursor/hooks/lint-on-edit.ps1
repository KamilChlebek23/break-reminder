# Per-edit ruff lint hook for Cursor's afterFileEdit event.
#
# Reads the hook payload from stdin, extracts the edited file path,
# and runs `uv run ruff check` on it when it's a Python source file.
# Exits 2 (blocking) on lint failures so the diagnostics are surfaced
# to the agent's context; exits 0 otherwise (success, non-Python, or
# unparseable payload — fail-open).

$ErrorActionPreference = 'Continue'

# Read the full stdin payload Cursor pipes to the hook.
$inputJson = [Console]::In.ReadToEnd()

$payload = $null
if ($inputJson) {
    try {
        $payload = $inputJson | ConvertFrom-Json -ErrorAction Stop
    } catch {
        exit 0
    }
}

# Try the field paths Cursor is known to expose for afterFileEdit.
# Order: explicit file_path, nested tool_input.file_path / .path, top-level path.
$filePath = $null
if ($payload) {
    foreach ($candidate in @(
        $payload.file_path,
        $payload.tool_input.file_path,
        $payload.tool_input.path,
        $payload.path
    )) {
        if ($candidate) { $filePath = [string]$candidate; break }
    }
}

if (-not $filePath) { exit 0 }
if ($filePath -notmatch '\.py$') { exit 0 }
if (-not (Test-Path $filePath)) { exit 0 }

# Run ruff scoped to the edited file. Ruff is fast (<200ms typical)
# so per-edit is a tolerable cost.
$output = & uv run ruff check $filePath 2>&1 | Out-String
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host "[lint-on-edit] ruff check failed on $filePath"
    Write-Host $output
    exit 2
}

exit 0
