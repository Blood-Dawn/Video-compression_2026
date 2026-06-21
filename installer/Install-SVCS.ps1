<#
.SYNOPSIS
    SVCS one-line installer / component menu (R3.2b), WinUtil style.

.DESCRIPTION
    Run from a fresh terminal:

        irm https://raw.githubusercontent.com/Blood-Dawn/Video-compression_2026/app/installer/Install-SVCS.ps1 | iex

    Presents a component-selection menu (a dark, amber-accented WPF window, or a
    text menu with -NoGui) and installs the selected pieces:

      core      SVCS core app   (required) - winget if available, else the
                                 GitHub Release installer run silently
      plates    AI plate reader (optional) - separate Python environment; this
                                 records the request and points at the docs
      mediamtx  Local RTSP server (optional) - downloads the MediaMTX binary into
                                 the app-data tools dir (same path the app uses)
      samples   Sample clips    (optional) - a couple of CDnet test clips

    -DryRun (alias -WhatIf) prints exactly what each selected component WOULD do
    without doing it. Only the core installer needs elevation (the Inno installer
    is per-machine); the optional components write into your user profile.

.PARAMETER NoGui
    Use the text menu instead of the WPF window (headless / SSH).

.PARAMETER DryRun
    Print actions without performing them. Alias: -WhatIf.

.PARAMETER Components
    Preselect components (skips the menu), e.g. -Components core,mediamtx.

.PARAMETER Tag
    GitHub Release tag that hosts the installer asset. Default v2.1.0.dev0.

.EXAMPLE
    pwsh installer/Install-SVCS.ps1

.EXAMPLE
    pwsh installer/Install-SVCS.ps1 -NoGui -DryRun

.EXAMPLE
    pwsh installer/Install-SVCS.ps1 -Components core,mediamtx
#>
[CmdletBinding()]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '',
    Justification = 'Interactive installer prints styled status to the console.')]
param(
    [switch]$NoGui,
    [Alias('WhatIf')]
    [switch]$DryRun,
    [string[]]$Components,
    [string]$Tag = 'v2.1.0.dev0'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── SVCS theme (dark base, amber accent) ──────────────────────────────────────
$Theme = @{
    Bg     = '#0a0e14'
    Panel  = '#11161f'
    Accent = '#ffb900'
    Fg     = '#e6e6e6'
    Dim    = '#8a93a3'
}

$Repo = 'Blood-Dawn/Video-compression_2026'
$WingetId = 'Blood-Dawn.SVCS'
$MediaMtxVersion = '1.9.3'
$Version = $Tag.TrimStart('v')

$AllComponents = @(
    [pscustomobject]@{ Key = 'core'; Name = 'SVCS core app';
        Required = $true;  Default = $true
        Desc = 'The app itself (bundles ffmpeg, the ONNX runtime, and the model).' }
    [pscustomobject]@{ Key = 'plates'; Name = 'AI plate reader (optional)';
        Required = $false; Default = $false
        Desc = 'License-plate super-resolution. Needs a SEPARATE Python env (easyocr/opencv conflict); this records the request and points at the docs.' }
    [pscustomobject]@{ Key = 'mediamtx'; Name = 'Local RTSP server (MediaMTX, optional)';
        Required = $false; Default = $false
        Desc = 'Downloads the MediaMTX binary into the app-data tools folder for local RTSP/HLS.' }
    [pscustomobject]@{ Key = 'samples'; Name = 'Sample clips (optional)';
        Required = $false; Default = $false
        Desc = 'A couple of CDnet surveillance clips to try compression on.' }
)

# ── helpers ───────────────────────────────────────────────────────────────────

function Write-Status {
    param([string]$Message, [string]$Color = 'Gray')
    # The theme hex values are for the WPF window; the console needs ConsoleColor
    # names, so map the palette (and pass plain names through).
    $map = @{
        $Theme.Accent = 'Yellow'
        $Theme.Dim    = 'DarkGray'
        $Theme.Fg     = 'Gray'
        $Theme.Panel  = 'Gray'
        $Theme.Bg     = 'Black'
    }
    $resolved = if ($map.ContainsKey($Color)) { $map[$Color] } else { $Color }
    Write-Host $Message -ForegroundColor $resolved
}

function Get-DataDir {
    Join-Path $env:LOCALAPPDATA 'SVCS\SVCS'
}

function Get-ToolsDir {
    Join-Path (Get-DataDir) 'tools'
}

function Get-VideosDir {
    Join-Path ([Environment]::GetFolderPath('MyVideos')) 'SVCS'
}

function Test-Winget {
    [bool](Get-Command winget -ErrorAction SilentlyContinue)
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltinRole]::Administrator)
}

function New-DirIfMissing {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

# ── component installers ──────────────────────────────────────────────────────

function Install-Core {
    param([switch]$DryRun)
    Write-Status 'SVCS core app' $Theme.Accent
    $installerUrl = "https://github.com/$Repo/releases/download/$Tag/SVCS-Setup-$Version.exe"
    if (Test-Winget) {
        if ($DryRun) {
            Write-Status "  WOULD run: winget install --id $WingetId -e" $Theme.Dim
            Write-Status "  (fallback if not yet public: download $installerUrl and run /VERYSILENT)" $Theme.Dim
            return
        }
        Write-Status "  winget install --id $WingetId" $Theme.Fg
        & winget install --id $WingetId -e --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) { Write-Status '  installed via winget.' 'Green'; return }
        Write-Status '  winget could not install it (manifest may not be public yet); using the GitHub Release.' 'Yellow'
    }
    else {
        Write-Status '  winget not found. Install "App Installer" from the Microsoft Store for winget support.' 'Yellow'
    }

    if ($DryRun) {
        Write-Status "  WOULD download $installerUrl and run it /VERYSILENT /SUPPRESSMSGBOXES /NORESTART (needs admin)." $Theme.Dim
        return
    }
    if (-not (Test-Admin)) {
        Write-Status '  NOTE: the installer is per-machine and needs an elevated (Run as administrator) terminal.' 'Yellow'
    }
    $tmp = Join-Path $env:TEMP "SVCS-Setup-$Version.exe"
    Write-Status "  downloading $installerUrl" $Theme.Fg
    Invoke-WebRequest -Uri $installerUrl -OutFile $tmp -UseBasicParsing
    # SEC-016: the download is over HTTPS from the official repo, but this path
    # (unlike winget, which pins InstallerSha256) cannot pin a per-release hash.
    # Surface the SHA256 so the operator can compare it against SHA256SUMS.txt on
    # the Release page before trusting the binary.
    $sha = (Get-FileHash -Algorithm SHA256 -Path $tmp).Hash
    Write-Status "  SHA256: $sha" $Theme.Dim
    Write-Status "  Verify this against SHA256SUMS.txt on the GitHub Release before trusting it." $Theme.Dim
    Write-Status '  running installer silently...' $Theme.Fg
    Start-Process -FilePath $tmp -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait
    Write-Status '  core install finished.' 'Green'
}

function Install-Plates {
    param([switch]$DryRun)
    Write-Status 'AI plate reader (optional)' $Theme.Accent
    $marker = Join-Path (Get-DataDir) 'plates_requested.txt'
    $docs = "https://github.com/$Repo/blob/main/docs"
    if ($DryRun) {
        Write-Status "  WOULD record a request marker at $marker and point you at $docs." $Theme.Dim
        Write-Status '  The plate reader runs in its OWN Python environment; it is not bundled in the core app.' $Theme.Dim
        return
    }
    New-DirIfMissing (Get-DataDir)
    Set-Content -Path $marker -Value "requested $((Get-Date).ToString('o'))" -Encoding utf8
    Write-Status "  recorded request at $marker" 'Green'
    Write-Status "  The plate reader needs a separate Python env (easyocr/opencv conflict). See $docs." $Theme.Fg
}

function Install-MediaMtx {
    param([switch]$DryRun)
    Write-Status 'Local RTSP server (MediaMTX)' $Theme.Accent
    $asset = "mediamtx_v${MediaMtxVersion}_windows_amd64.zip"
    $url = "https://github.com/bluenviron/mediamtx/releases/download/v$MediaMtxVersion/$asset"
    $tools = Get-ToolsDir
    if ($DryRun) {
        Write-Status "  WOULD download $url" $Theme.Dim
        Write-Status "  WOULD extract mediamtx.exe into $tools" $Theme.Dim
        return
    }
    New-DirIfMissing $tools
    $zip = Join-Path $env:TEMP $asset
    Write-Status "  downloading $url" $Theme.Fg
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Write-Status "  extracting into $tools" $Theme.Fg
    Expand-Archive -Path $zip -DestinationPath $tools -Force
    Write-Status '  MediaMTX ready.' 'Green'
}

function Install-Samples {
    param([switch]$DryRun)
    Write-Status 'Sample clips' $Theme.Accent
    $videos = Get-VideosDir
    $base = "https://media.githubusercontent.com/media/$Repo/app/data/samples/cdnet_mp4/baseline"
    $clips = @('baseline_highway.mp4', 'baseline_pedestrians.mp4')
    if ($DryRun) {
        foreach ($c in $clips) {
            Write-Status "  WOULD download $base/$c into $videos" $Theme.Dim
        }
        return
    }
    New-DirIfMissing $videos
    foreach ($c in $clips) {
        $dst = Join-Path $videos $c
        try {
            Write-Status "  downloading $c" $Theme.Fg
            Invoke-WebRequest -Uri "$base/$c" -OutFile $dst -UseBasicParsing
        }
        catch {
            Write-Status "  could not fetch $c ($($_.Exception.Message)). Skipping." 'Yellow'
        }
    }
    Write-Status "  sample clips in $videos" 'Green'
}

function Invoke-Components {
    param([string[]]$Keys, [switch]$DryRun)
    if (-not $Keys -or $Keys.Count -eq 0) {
        Write-Status 'Nothing selected. Exiting.' 'Yellow'
        return
    }
    if ($DryRun) { Write-Status 'DRY RUN - no changes will be made.' $Theme.Accent }
    # core first if present
    $ordered = @('core', 'plates', 'mediamtx', 'samples') | Where-Object { $Keys -contains $_ }
    foreach ($key in $ordered) {
        switch ($key) {
            'core' { Install-Core -DryRun:$DryRun }
            'plates' { Install-Plates -DryRun:$DryRun }
            'mediamtx' { Install-MediaMtx -DryRun:$DryRun }
            'samples' { Install-Samples -DryRun:$DryRun }
        }
    }
    Write-Status '' 'Gray'
    Write-Status 'Done. Launch SVCS from the Start menu, or run the app and open http://127.0.0.1:5000' $Theme.Accent
}

# ── text menu (-NoGui) ────────────────────────────────────────────────────────

function Show-ConsoleMenu {
    Write-Status '' 'Gray'
    Write-Status '  SVCS installer' $Theme.Accent
    Write-Status '  Surveillance Video Compression System' $Theme.Dim
    Write-Status '' 'Gray'
    $selected = [System.Collections.Generic.List[string]]::new()
    foreach ($c in $AllComponents) {
        if ($c.Required) {
            $selected.Add($c.Key)
            Write-Status ("  [x] {0} (required)" -f $c.Name) $Theme.Fg
            Write-Status ("      {0}" -f $c.Desc) $Theme.Dim
            continue
        }
        $ans = Read-Host ("  Install '{0}'? {1} [y/N]" -f $c.Name, $c.Desc)
        if ($ans -match '^(y|yes)$') { $selected.Add($c.Key) }
    }
    return $selected.ToArray()
}

# ── WPF menu (default) ────────────────────────────────────────────────────────

function Show-GuiMenu {
    Add-Type -AssemblyName PresentationFramework
    $rows = ''
    foreach ($c in $AllComponents) {
        $checked = if ($c.Default) { 'IsChecked="True"' } else { '' }
        $enabled = if ($c.Required) { 'IsEnabled="False"' } else { '' }
        $rows += @"
        <Border Background="$($Theme.Panel)" CornerRadius="4" Padding="10" Margin="0,4">
          <StackPanel>
            <CheckBox x:Name="cb_$($c.Key)" $checked $enabled Foreground="$($Theme.Fg)" FontWeight="Bold" Content="$($c.Name)"/>
            <TextBlock Foreground="$($Theme.Dim)" TextWrapping="Wrap" Margin="22,2,0,0" Text="$($c.Desc)"/>
          </StackPanel>
        </Border>
"@
    }
    [xml]$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="SVCS installer" Height="520" Width="560"
        WindowStartupLocation="CenterScreen" Background="$($Theme.Bg)">
  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>
    <StackPanel Grid.Row="0" Margin="0,0,0,10">
      <TextBlock Text="SVCS" Foreground="$($Theme.Accent)" FontSize="26" FontWeight="Bold"/>
      <TextBlock Text="Surveillance Video Compression System - choose what to install" Foreground="$($Theme.Dim)"/>
    </StackPanel>
    <ScrollViewer Grid.Row="1" VerticalScrollBarVisibility="Auto">
      <StackPanel>
$rows
      </StackPanel>
    </ScrollViewer>
    <StackPanel Grid.Row="2" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,12,0,0">
      <Button x:Name="btnCancel" Content="Cancel" Width="90" Height="32" Margin="0,0,8,0"/>
      <Button x:Name="btnInstall" Content="Install selected" Width="140" Height="32"
              Background="$($Theme.Accent)" Foreground="$($Theme.Bg)" FontWeight="Bold"/>
    </StackPanel>
  </Grid>
</Window>
"@
    $reader = New-Object System.Xml.XmlNodeReader $xaml
    $window = [Windows.Markup.XamlReader]::Load($reader)
    $script:guiResult = @()
    $btnInstall = $window.FindName('btnInstall')
    $btnCancel = $window.FindName('btnCancel')
    $btnInstall.Add_Click({
            $picked = [System.Collections.Generic.List[string]]::new()
            foreach ($c in $AllComponents) {
                $cb = $window.FindName("cb_$($c.Key)")
                if ($c.Required -or ($cb -and $cb.IsChecked)) { $picked.Add($c.Key) }
            }
            $script:guiResult = $picked.ToArray()
            $window.Close()
        })
    $btnCancel.Add_Click({ $script:guiResult = @(); $window.Close() })
    $window.ShowDialog() | Out-Null
    return $script:guiResult
}

# ── main ──────────────────────────────────────────────────────────────────────

Write-Status '' 'Gray'
Write-Status 'SVCS installer (Surveillance Video Compression System)' $Theme.Accent

if ($Components) {
    Invoke-Components -Keys $Components -DryRun:$DryRun
    return
}

$selection = @()
if ($NoGui) {
    $selection = Show-ConsoleMenu
}
else {
    try {
        $selection = Show-GuiMenu
    }
    catch {
        Write-Status "GUI unavailable ($($_.Exception.Message)); falling back to the text menu." 'Yellow'
        $selection = Show-ConsoleMenu
    }
}

Invoke-Components -Keys $selection -DryRun:$DryRun
