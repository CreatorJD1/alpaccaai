[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$SpaceRepo = "CREATORJD/alpecca-survival-core",
    [string]$GatewayBaseUrl = "https://alpecca-continuity-gateway.pages.dev/language/v1"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$workerRoot = Join-Path $repoRoot "deploy\cloud-language-worker"
$gatewayRoot = Join-Path $repoRoot "deploy\continuity-pages-gateway"
$wrangler = Join-Path $workerRoot "node_modules\.bin\wrangler.cmd"

if (-not $Apply) {
    [pscustomobject]@{
        applyRequired = $true
        worker = "alpecca-cloud-language"
        gateway = "alpecca-continuity-gateway"
        spaceRepo = $SpaceRepo
        fallbackUrl = $GatewayBaseUrl
        model = "@cf/google/gemma-4-26b-a4b-it"
        secretHandling = "generated once; uploaded to Worker and Space; temporary file removed"
    } | ConvertTo-Json -Depth 3
    exit 0
}

foreach ($required in @($workerRoot, $gatewayRoot, $wrangler)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required deployment path is missing: $required"
    }
}

$fallbackUri = [Uri]$GatewayBaseUrl
if ($fallbackUri.Scheme -ne "https" -or -not $fallbackUri.Host -or $fallbackUri.Query -or $fallbackUri.Fragment) {
    throw "GatewayBaseUrl must be a credential-free HTTPS URL"
}

$secretBytes = New-Object byte[] 48
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $rng.GetBytes($secretBytes)
}
finally {
    $rng.Dispose()
}
$sharedSecret = [Convert]::ToBase64String($secretBytes)

$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$secretPath = Join-Path $tempRoot ("alpecca-language-" + [Guid]::NewGuid().ToString("N") + ".env")
$secretPath = [System.IO.Path]::GetFullPath($secretPath)
if (-not $secretPath.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing an unsafe temporary secret path"
}

$utf8 = New-Object System.Text.UTF8Encoding($false)
$previousLocation = Get-Location
try {
    [System.IO.File]::WriteAllText(
        $secretPath,
        "LANGUAGE_AUTH_SECRET=$sharedSecret`n",
        $utf8
    )

    Set-Location -LiteralPath $workerRoot
    & $wrangler deploy --secrets-file $secretPath
    if ($LASTEXITCODE -ne 0) {
        throw "Cloud language Worker deployment failed"
    }

    Set-Location -LiteralPath $gatewayRoot
    & $wrangler pages deploy public --project-name alpecca-continuity-gateway --branch main
    if ($LASTEXITCODE -ne 0) {
        throw "Continuity Pages gateway deployment failed"
    }

    $env:ALPECCA_LANGUAGE_ROUTE_SECRET = $sharedSecret
    $env:ALPECCA_LANGUAGE_ROUTE_SPACE = $SpaceRepo
    $env:ALPECCA_LANGUAGE_ROUTE_URL = $GatewayBaseUrl
    @'
import os
import json
import time
import urllib.error
import urllib.request
from huggingface_hub import HfApi

secret = os.environ.get("ALPECCA_LANGUAGE_ROUTE_SECRET", "")
repo = os.environ.get("ALPECCA_LANGUAGE_ROUTE_SPACE", "")
url = os.environ.get("ALPECCA_LANGUAGE_ROUTE_URL", "")
if len(secret) < 32 or not repo or not url.startswith("https://"):
    raise SystemExit("guarded language-route values are incomplete")

health_url = url.rsplit("/v1", 1)[0] + "/healthz"
user_agent = "Mozilla/5.0 (compatible; AlpeccaCloudLanguage/1.0)"
with urllib.request.urlopen(
    urllib.request.Request(health_url, headers={"User-Agent": user_agent}),
    timeout=20,
) as response:
    health = json.loads(response.read().decode("utf-8"))
if not (
    health.get("service") == "alpecca-cloud-language"
    and health.get("ready") is True
    and health.get("contextWindowTokens") == 256000
):
    raise SystemExit("language-route health contract did not match")

body = json.dumps({
    "model": "@cf/google/gemma-4-26b-a4b-it",
    "messages": [{"role": "user", "content": "Reply with exactly ALPECCA_ROUTE_OK."}],
    "max_tokens": 128,
    "temperature": 0,
}).encode("utf-8")
try:
    urllib.request.urlopen(
        urllib.request.Request(
            url + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": user_agent},
            method="POST",
        ),
        timeout=20,
    )
    raise SystemExit("unauthenticated language request unexpectedly succeeded")
except urllib.error.HTTPError as exc:
    if exc.code != 401:
        raise

completion = None
last_status = None
for attempt in range(15):
    request = urllib.request.Request(
        url + "/chat/completions",
        data=body,
        headers={
            "Authorization": "Bearer " + secret,
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            completion = json.loads(response.read().decode("utf-8"))
        break
    except urllib.error.HTTPError as exc:
        last_status = exc.code
        if exc.code not in {401, 404, 503} or attempt == 14:
            raise
        time.sleep(2)
if not isinstance(completion, dict):
    raise SystemExit(f"authenticated language route unavailable: {last_status}")
choice = (completion.get("choices") or [{}])[0]
message = choice.get("message") if isinstance(choice, dict) else {}
content = message.get("content") if isinstance(message, dict) else ""
if not isinstance(content, str) or not content.strip():
    raise SystemExit("authenticated language route returned no text")
print(json.dumps({
    "language_route_live": True,
    "health_status": 200,
    "unauthorized_status": 401,
    "authenticated_status": 200,
    "response_characters": len(content),
    "finish_reason": choice.get("finish_reason"),
    "model": completion.get("model"),
}, sort_keys=True))

api = HfApi()
api.add_space_secret(repo, "ALPECCA_HF_FALLBACK_API_KEY", secret)
api.add_space_variable(repo, "ALPECCA_HF_FALLBACK_URL", url)
api.add_space_variable(
    repo,
    "ALPECCA_HF_FALLBACK_MODEL",
    "@cf/google/gemma-4-26b-a4b-it",
)
print("hf_space_language_route_configured=true")
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        throw "Hugging Face Space language-route configuration failed"
    }

    [pscustomobject]@{
        ok = $true
        worker = "alpecca-cloud-language"
        gateway = "alpecca-continuity-gateway"
        spaceRepo = $SpaceRepo
        fallbackUrl = $GatewayBaseUrl
        model = "@cf/google/gemma-4-26b-a4b-it"
        secretPrinted = $false
    } | ConvertTo-Json -Depth 3
}
finally {
    Set-Location -LiteralPath $previousLocation
    Remove-Item Env:ALPECCA_LANGUAGE_ROUTE_SECRET -ErrorAction SilentlyContinue
    Remove-Item Env:ALPECCA_LANGUAGE_ROUTE_SPACE -ErrorAction SilentlyContinue
    Remove-Item Env:ALPECCA_LANGUAGE_ROUTE_URL -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $secretPath) {
        Remove-Item -LiteralPath $secretPath -Force
    }
    $sharedSecret = $null
    [Array]::Clear($secretBytes, 0, $secretBytes.Length)
}
