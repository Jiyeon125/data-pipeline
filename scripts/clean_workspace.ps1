[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$IncludeBrokenVenv
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$targets = @(
    (Join-Path $root "tmp"),
    (Join-Path $root ".ruff_cache"),
    (Join-Path $root "src\open_fiscal_data_pipeline.egg-info")
)

$targets += Get-ChildItem -LiteralPath $root -Directory -Force |
    Where-Object { $_.Name -like ".pytest*" } |
    ForEach-Object { $_.FullName }

$targets += Get-ChildItem -LiteralPath @(
    (Join-Path $root "src"),
    (Join-Path $root "tests"),
    (Join-Path $root "scripts")
) -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object { $_.FullName }

if ($IncludeBrokenVenv) {
    $targets += Join-Path $root ".venv.broken"
}

foreach ($target in $targets | Select-Object -Unique) {
    if (-not (Test-Path -LiteralPath $target)) {
        continue
    }

    $resolved = (Resolve-Path -LiteralPath $target).Path
    if (-not $resolved.StartsWith(
        $root + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing to remove a path outside the workspace: $resolved"
    }

    if ($PSCmdlet.ShouldProcess($resolved, "Remove generated workspace files")) {
        try {
            Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction Stop
            Write-Output "removed`t$resolved"
        }
        catch {
            Write-Warning "Could not remove this path. Close related Python/VS Code processes and retry: $resolved"
        }
    }
}
