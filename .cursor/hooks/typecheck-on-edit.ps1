# Per-edit pyright typecheck hook for Cursor's afterFileEdit event.
#
# Reads the hook payload from stdin, extracts the edited file path,
# and runs `uv run pyright` on it when it's a Python source file.
# Exits 2 (blocking) on type errors so the diagnostics are surfaced
# to the agent's context; exits 0 otherwise (success, non-Python, or
# unparseable payload — fail-open).
#
# Per AGENTS.md: pyright per-file is fast enough for this codebase
# (~10 source files). If the project grows and this slows the agent
# down, move the typecheck into pre-commit and keep only ruff per-edit.

$ErrorActionPreference = 'Continue'

$inputJson = [Console]::In.ReadToEnd()

$payload = $null
if ($inputJson) {
    try {
        $payload = $inputJson | ConvertFrom-Json -ErrorAction Stop
    } catch {
        exit 0
    }
}

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

$output = & uv run pyright $filePath 2>&1 | Out-String
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host "[typecheck-on-edit] pyright failed on $filePath"
    Write-Host $output
    exit 2
}

exit 0
