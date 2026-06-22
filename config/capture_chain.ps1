$callback = [System.Net.Security.RemoteCertificateValidationCallback]{
    param($sender, $cert, $chain, $errors)
    $chain.ChainElements | ForEach-Object -Begin { $i = 0 } -Process {
        $c = $_.Certificate
        Write-Host ("Chain[$i]: " + $c.Subject)
        $bytes = $c.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert)
        [System.IO.File]::WriteAllBytes("C:\Claude\kestrel\config\chain_cert_$i.der", $bytes)
        $i++
    }
    return $true
}
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = $callback
try {
    $req = [System.Net.WebRequest]::Create('https://api.anthropic.com')
    $req.Method = 'HEAD'
    $req.Timeout = 8000
    try { $req.GetResponse() | Out-Null } catch {}
    Write-Host 'Chain captured'
} finally {
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = $null
}

# Convert chain[1] and chain[2] (CA certs) to PEM
foreach ($i in 1,2) {
    $der = [System.IO.File]::ReadAllBytes("C:\Claude\kestrel\config\chain_cert_$i.der")
    $b64 = [Convert]::ToBase64String($der)
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("-----BEGIN CERTIFICATE-----")
    for ($j = 0; $j -lt $b64.Length; $j += 64) {
        $lines.Add($b64.Substring($j, [Math]::Min(64, $b64.Length - $j)))
    }
    $lines.Add("-----END CERTIFICATE-----")
    $pem = $lines -join "`r`n"
    [System.IO.File]::WriteAllText("C:\Claude\kestrel\config\chain_cert_$i.pem", $pem, [System.Text.Encoding]::ASCII)
    Write-Host ("chain_cert_$i.pem written (" + $der.Length + " bytes)")
}
