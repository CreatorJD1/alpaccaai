[CmdletBinding()]
param(
    [switch]$PrepareClient,
    [switch]$InstallServer,
    [switch]$Status,
    [string]$PublicKeyPath = '',
    [string]$RemoteUser = $env:USERNAME
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedServer = 'Jason_HOLYROG'
$AdminDir = Join-Path $env:LOCALAPPDATA 'Alpecca\rog-admin'
$PrivateKey = Join-Path $AdminDir 'id_ed25519'
$PublicKey = "$PrivateKey.pub"
$KnownHosts = Join-Path $AdminDir 'known_hosts'
$TaskHost = [System.Net.Dns]::GetHostName()

if (@($PrepareClient, $InstallServer, $Status | Where-Object { $_ }).Count -ne 1) {
    throw 'Choose exactly one of -PrepareClient, -InstallServer, or -Status.'
}

if ($PrepareClient) {
    New-Item -ItemType Directory -Path $AdminDir -Force | Out-Null
    $sshKeygen = (Get-Command ssh-keygen.exe -ErrorAction Stop).Source
    if (-not (Test-Path -LiteralPath $PrivateKey -PathType Leaf)) {
        & $sshKeygen -t ed25519 -a 64 -N '' -C 'Alpecca CreatorJD ROG development' -f $PrivateKey
        if ($LASTEXITCODE -ne 0) { throw 'Could not generate the ROG development key.' }
    }
    Write-Host "Client key ready. Public key: $PublicKey"
    Write-Host "Install that public key on $ExpectedServer with -InstallServer."
    exit 0
}

if ($InstallServer) {
    if (-not [string]::Equals($TaskHost, $ExpectedServer, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Server enrollment must run on $ExpectedServer; this computer is $TaskHost."
    }
    if (-not $PublicKeyPath -or -not (Test-Path -LiteralPath $PublicKeyPath -PathType Leaf)) {
        throw '-PublicKeyPath must name the CreatorJD public key copied from the primary computer.'
    }
    $public = (Get-Content -LiteralPath $PublicKeyPath -Raw).Trim()
    if ($public -notmatch '^ssh-ed25519\s+[A-Za-z0-9+/=]+(?:\s+.*)?$') {
        throw 'The supplied CreatorJD public key is invalid.'
    }

    $capability = Get-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0'
    if ($capability.State -ne 'Installed') {
        Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' | Out-Null
    }
    Set-Service -Name sshd -StartupType Automatic
    Start-Service -Name sshd

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isAdmin) {
        $authFile = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
        New-Item -ItemType Directory -Path (Split-Path $authFile) -Force | Out-Null
        Set-Content -LiteralPath $authFile -Value $public -Encoding ascii
        & icacls.exe $authFile /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
    } else {
        $sshDir = Join-Path $env:USERPROFILE '.ssh'
        $authFile = Join-Path $sshDir 'authorized_keys'
        New-Item -ItemType Directory -Path $sshDir -Force | Out-Null
        Set-Content -LiteralPath $authFile -Value $public -Encoding ascii
        & icacls.exe $sshDir /inheritance:r /grant "$RemoteUser`:F" /grant 'SYSTEM:F' | Out-Null
        & icacls.exe $authFile /inheritance:r /grant "$RemoteUser`:F" /grant 'SYSTEM:F' | Out-Null
    }

    Get-NetFirewallRule -DisplayName 'Alpecca ROG SSH over Tailscale' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName 'Alpecca ROG SSH over Tailscale' `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22 `
        -InterfaceAlias 'Tailscale' -Profile Any | Out-Null
    Write-Host "ROG administrator SSH is installed for $RemoteUser on the private Tailscale interface."
    exit 0
}

if ($Status) {
    [pscustomobject]@{
        Computer = $TaskHost
        ClientKey = Test-Path -LiteralPath $PrivateKey -PathType Leaf
        KnownHosts = Test-Path -LiteralPath $KnownHosts -PathType Leaf
        Sshd = (Get-Service sshd -ErrorAction SilentlyContinue).Status
        Port22 = (Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue) -ne $null
    }
}
