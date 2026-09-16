param([switch]$Check)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$runtime = Join-Path $root 'runtime'
try {
    if ($root.StartsWith('\\')) { throw 'Please extract to a local disk, not a network share.' }
    $marker = Join-Path $runtime '.portable-ready'
    if (!(Test-Path -LiteralPath $marker)) {
        Write-Host 'First start: preparing the included runtime. Please wait (no download needed)...'
        if (Test-Path -LiteralPath $runtime) { throw 'Incomplete runtime found. Extract the original ZIP to a new folder and retry.' }
        Expand-Archive -LiteralPath (Join-Path $root 'runtime.zip') -DestinationPath $runtime
        $env:PATH = "$runtime;$runtime\Library\bin;$runtime\Scripts;$env:SystemRoot\System32;$env:SystemRoot"
        $env:PYTHONUTF8 = '1'
        $env:PYTHONHOME = $null
        $env:PYTHONPATH = $null
        $env:PYTHONNOUSERSITE = '1'
        & "$runtime\python.exe" "$runtime\Scripts\conda-unpack-script.py"
        if ($LASTEXITCODE -ne 0) { throw 'Runtime preparation failed. Extract to a new folder and retry.' }
        Set-Content -LiteralPath $marker -Value $root -Encoding UTF8
    }
    if ((Get-Content -LiteralPath $marker -Raw).Trim() -ne $root) { throw 'Folder moved after first start. Extract the original ZIP again at the new location.' }
    $env:PATH = "$runtime;$runtime\Library\bin;$runtime\Scripts;$env:SystemRoot\System32;$env:SystemRoot"
    $env:PYTHONHOME = $null
    $env:PYTHONPATH = $null
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONUTF8 = '1'
    $env:SPIDER_PORT = '18765'
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $root 'browsers'
    $env:CRAWL4_AI_BASE_DIRECTORY = Join-Path $root 'user-data'
    Set-Location -LiteralPath (Join-Path $root 'app')
    if ($Check) {
        & "$runtime\python.exe" portable_check.py
        if ($LASTEXITCODE -ne 0) { throw 'Portable self-test failed.' }
        exit 0
    }
    Write-Host 'Opening http://127.0.0.1:18765 - keep this window open while using the app.'
    & "$runtime\python.exe" launcher.py
    if ($LASTEXITCODE -ne 0) { throw 'Application stopped with an error. Keep this window and send a screenshot.' }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
