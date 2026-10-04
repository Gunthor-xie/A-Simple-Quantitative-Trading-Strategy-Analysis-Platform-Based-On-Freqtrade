# Second-pass GitHub data collection for the quant research note.
# Usage: pwsh -File fetch-repos.ps1
$ErrorActionPreference = 'Continue'
$root = 'D:/Documents/ChatGPT/Freqtrade/.scratch/quant-research/raw'
New-Item -ItemType Directory -Force $root | Out-Null

$headers = @{ 'Accept' = 'application/vnd.github+json'; 'User-Agent' = 'quant-research' }

# --- extra repository searches -------------------------------------------------
$searches = [ordered]@{
  s9  = 'topic:crypto-trading-bot'
  s10 = 'topic:trading-strategy'
  s11 = 'topic:factor-investing'
  s12 = 'quantitative trading strategy'
  s13 = 'algorithmic trading strategies'
  s14 = 'financial reinforcement learning'
}
foreach ($k in $searches.Keys) {
  $out = Join-Path $root "$k.json"
  $url = "https://api.github.com/search/repositories?q=$($searches[$k])&sort=stars&order=desc&per_page=30"
  curl.exe -s -m 40 -H "Accept: application/vnd.github+json" $url -o $out
  $len = (Get-Item $out).Length
  Write-Output ("search {0} -> {1} ({2} bytes)" -f $k, $searches[$k], $len)
  Start-Sleep -Seconds 7
}

# --- targeted repo lookups -----------------------------------------------------
$repos = @(
  'vnpy/vnpy',
  'nautechsystems/nautilus_trader',
  'ccxt/ccxt',
  'robcarver17/pysystemtrade',
  'QUANTAXIS/QUANTAXIS',
  'wondertrader/wondertrader',
  'Drakkar-Software/OctoBot',
  'blankly-finance/blankly',
  'stefan-jansen/zipline-reloaded',
  'pmorissette/bt',
  'twopirllc/pandas-ta',
  'hudson-and-thames/mlfinlab',
  'robertmartin8/PyPortfolioOpt',
  'ranaroussi/quantstats',
  'polakowo/vectorbt',
  'kernc/backtesting.py',
  'jesse-ai/jesse',
  'je-suis-tm/quant-trading',
  'hugo2046/QuantsPlaybook',
  'freqtrade/freqtrade-strategies',
  'AI4Finance-Foundation/FinRobot',
  'AI4Finance-Foundation/FinGPT',
  'quantopian/pyfolio',
  'quantopian/alphalens',
  'quantopian/empyrical',
  'microsoft/qlib',
  'hummingbot/hummingbot',
  'OpenBB-finance/OpenBB',
  'firmai/financial-machine-learning',
  'nkaz001/hftbacktest',
  'quantaxis/qapro',
  'paperswithbacktest/awesome-systematic-trading',
  'edtechre/pybroker',
  'ranaroussi/yfinance',
  'quantopian/zipline',
  'mementum/backtrader',
  'QuantConnect/Lean',
  'stefan-jansen/machine-learning-for-trading'
)

$out = Join-Path $root 'repos.jsonl'
Remove-Item -Force $out -ErrorAction SilentlyContinue
foreach ($r in $repos) {
  $tmp = Join-Path $env:TEMP 'repo.json'
  curl.exe -s -m 30 -H "Accept: application/vnd.github+json" "https://api.github.com/repos/$r" -o $tmp
  $j = Get-Content $tmp -Raw | ConvertFrom-Json
  if ($j.full_name) {
    $o = [pscustomobject]@{
      repo      = $j.full_name
      stars     = $j.stargazers_count
      forks     = $j.forks_count
      lang      = $j.language
      pushed    = $j.pushed_at
      created   = $j.created_at
      license   = $j.license.spdx_id
      archived  = $j.archived
      open_iss  = $j.open_issues_count
      topics    = ($j.topics -join ',')
      desc      = $j.description
      url       = $j.html_url
    }
    Write-Output ("ok   {0,-48} {1,7} stars" -f $o.repo, $o.stars)
  } else {
    Write-Output ("FAIL {0}" -f $r)
    $o = [pscustomobject]@{ repo = $r; stars = $null; forks = $null; lang = $null; pushed = $null; created = $null; license = $null; archived = $null; open_iss = $null; topics = $null; desc = $null; url = $null }
  }
  ($o | ConvertTo-Json -Compress) | Add-Content -Encoding UTF8 $out
}
Write-Output ("wrote {0}" -f $out)
