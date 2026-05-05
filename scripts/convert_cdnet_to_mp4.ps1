$ErrorActionPreference = 'Continue'

$outRoot = 'data/samples/cdnet_mp4'
New-Item -ItemType Directory -Force -Path $outRoot | Out-Null

$inputs = Get-ChildItem -Path 'data/dataset' -Recurse -Directory -Filter input
$ok = 0
$fail = 0

foreach ($inp in $inputs) {
    $scene = $inp.Parent.Name
    $cat = $inp.Parent.Parent.Name
    $out = Join-Path $outRoot ("{0}_{1}.mp4" -f $cat, $scene)

    $jpgFirst = Join-Path $inp.FullName 'in000001.jpg'
    $pngFirst = Join-Path $inp.FullName 'in000001.png'
    $jpgPattern = Join-Path $inp.FullName 'in%06d.jpg'
    $pngPattern = Join-Path $inp.FullName 'in%06d.png'

    if (Test-Path $jpgFirst) {
        ffmpeg -y -loglevel error -framerate 25 -start_number 1 -i "$jpgPattern" -c:v libx264 -pix_fmt yuv420p -crf 18 -preset veryfast "$out"
    }
    elseif (Test-Path $pngFirst) {
        ffmpeg -y -loglevel error -framerate 25 -start_number 1 -i "$pngPattern" -c:v libx264 -pix_fmt yuv420p -crf 18 -preset veryfast "$out"
    }
    else {
        Write-Host "SKIP no matching frame pattern: $($inp.FullName)"
        $fail++
        continue
    }

    if ($LASTEXITCODE -eq 0 -and (Test-Path $out)) {
        $ok++
        Write-Host "OK   $cat/$scene -> $out"
    }
    else {
        $fail++
        Write-Host "FAIL $cat/$scene"
    }
}

Write-Host "DONE. Converted=$ok Failed=$fail Output=$outRoot"
