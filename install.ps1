$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Package = "hound-tracer"
$Version = $env:HOUND_VERSION

function Stop-Install([string]$Message) {
    Write-Error $Message
    exit 1
}

if ($PSVersionTable.PSVersion.Major -lt 5) {
    Stop-Install "PowerShell 5.1 or later is required."
}

$activeHound = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    ($_.Name -in @("hound.exe", "hound-mcp.exe")) -or
    ($_.CommandLine -and $_.CommandLine -match "[\\/]hound-mcp(?:\.exe)?(?:\s|$)") -or
    ($_.ExecutablePath -and $_.ExecutablePath -match "[\\/]uv[\\/]tools[\\/]hound-tracer[\\/]")
})

if ($activeHound.Count -gt 0) {
    $processes = ($activeHound | ForEach-Object { "$($_.Name) (PID $($_.ProcessId))" }) -join ", "
    Stop-Install "Hound is running: $processes. Close the listed process or its host application, then run this installer again."
}

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCommand) {
    Write-Host "Installing uv..."
    $uvInstaller = Invoke-RestMethod https://astral.sh/uv/install.ps1
    Invoke-Expression $uvInstaller

    $candidates = @(
        (Join-Path $HOME ".local\bin\uv.exe"),
        (Join-Path $HOME ".cargo\bin\uv.exe")
    )
    $uvPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $uvPath) {
        Stop-Install "uv was installed but could not be found. Open a new PowerShell window and run this installer again."
    }
} else {
    $uvPath = $uvCommand.Source
}

$spec = if ($Version) { "${Package}==${Version}" } else { $Package }
Write-Host "Installing $spec..."
& $uvPath tool install --force $spec
if ($LASTEXITCODE -ne 0) {
    Stop-Install "uv could not install $spec."
}

$binDir = (& $uvPath tool dir --bin).Trim()
$houndPath = Join-Path $binDir "hound.exe"
if (-not (Test-Path $houndPath)) {
    Stop-Install "Installation completed but $houndPath was not created."
}

Write-Host ""
& $houndPath --version
if ($LASTEXITCODE -ne 0) {
    Stop-Install "Hound was installed but version verification failed."
}

Write-Host "Installed successfully."
$pathEntries = $env:PATH -split ";"
if ($pathEntries -contains $binDir) {
    Write-Host "Run: hound doctor"
} else {
    Write-Host "Open a new PowerShell window, then run: hound doctor"
}
