# Optional one-time online provenance check. No image/PDF is written to disk.
$ErrorActionPreference = 'Stop'
$registryPath = Join-Path $PSScriptRoot 'cases.jsonl'
$cases = Get-Content -LiteralPath $registryPath | ForEach-Object { $_ | ConvertFrom-Json }
$results = $cases | ForEach-Object -Parallel {
    $case = $_
    try {
        if ($case.source_group -eq 'belzona') {
            $page = Invoke-WebRequest -Uri $case.source_url -TimeoutSec 25
            $number = [regex]::Match($case.photo_locator, 'photograph (\d+)').Groups[1].Value
            $pattern = '/images/khia_images/[^\s"''<>]+/Main/[^\s"''<>]+_' + $number + '\.jpg'
            $match = [regex]::Match($page.Content, $pattern)
            if (-not $match.Success) { throw 'Photograph locator missing in page HTML' }
            $case.media_url = 'https://khia.belzona.com' + $match.Value
        }
        $media = Invoke-WebRequest -Uri $case.media_url -TimeoutSec 25
        $case.source_check.http_status = [int]$media.StatusCode
        $case.source_check.content_type = [string]($media.Headers['Content-Type'] -join ';')
        $case.source_check.bytes = $media.RawContentLength
        $case.source_check.method = 'public_page_caption_and_media_http_get_no_persisted_original'
    } catch {
        $case.source_check.http_status = 0
        $case.source_check.content_type = $_.Exception.Message
        $case.source_check.bytes = 0
    }
    $case
} -ThrottleLimit 6
$results | Sort-Object case_id | ForEach-Object { $_ | ConvertTo-Json -Depth 10 -Compress } | Set-Content -LiteralPath $registryPath -Encoding utf8NoBOM
$results | Where-Object { $_.source_check.http_status -ne 200 } | Select-Object case_id, media_url, @{Name='error';Expression={$_.source_check.content_type}}
Write-Output ('Verified media: ' + @($results | Where-Object { $_.source_check.http_status -eq 200 }).Count + '/' + $cases.Count)
