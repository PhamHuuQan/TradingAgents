param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9]{2,12}$')]
    [string]$Symbol,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$FromDate,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$ToDate,
    [ValidateRange(1, 1000)]
    [int]$PageSize = 100
)

$ErrorActionPreference = "Stop"
$names = @("SSI_API_KEY", "SSI_API_SECRET")
$previous = @{}

function Convert-SecureStringToPlainText([System.Security.SecureString]$SecureValue) {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

foreach ($name in $names) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

$exitCode = 0
try {
    foreach ($name in $names) {
        $currentValue = [Environment]::GetEnvironmentVariable($name, "Process")
        if ([string]::IsNullOrWhiteSpace($currentValue)) {
            $secureValue = Read-Host -AsSecureString "Enter $name (input is hidden)"
            try {
                if ($secureValue.Length -eq 0) {
                    throw "$name cannot be empty."
                }
                $plainValue = Convert-SecureStringToPlainText $secureValue
                [Environment]::SetEnvironmentVariable($name, $plainValue, "Process")
                $plainValue = $null
            }
            finally {
                $secureValue.Dispose()
            }
        }
    }

    Write-Host "Running read-only SSI connectivity check for $Symbol ($FromDate through $ToDate)."
    Write-Host "Credentials will not be printed or written to a file by this script."
    python -m tradingagents.dataflows.vietnam_market.smoke --symbol $Symbol --from-date $FromDate --to-date $ToDate --page-size $PageSize
    $exitCode = $LASTEXITCODE
}
catch {
    Write-Error $_.Exception.Message
    $exitCode = 1
}
finally {
    foreach ($name in $names) {
        if ($null -eq $previous[$name]) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
        else {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], "Process")
        }
    }
}
exit $exitCode
