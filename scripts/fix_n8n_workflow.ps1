param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputPath
)

$workflow = Get-Content -LiteralPath $InputPath -Raw | ConvertFrom-Json

function Get-Node([string]$Name) {
    $node = $workflow.nodes | Where-Object { $_.name -eq $Name }
    if (-not $node) { throw "Missing n8n node: $Name" }
    return $node
}

$builder = @'
function compactMoney(v) {
  const s = String(v || '').trim();
  if (!s || /not specified|n\/a/i.test(s)) return '';
  return s.replace(/\s+/g, ' ');
}

function priceCap(dealSize, criteria) {
  const direct = compactMoney(dealSize);
  if (direct) return direct;
  const text = String(criteria || '');
  const m = text.match(/(?:purchase|asking|deal)?\s*price[^$0-9]{0,30}(?:up to|under|below|max(?:imum)?)?\s*(\$?\s*[0-9][0-9,.]*\s*(?:m|mm|k|million|thousand)?)/i)
    || text.match(/(?:up to|under|below|max(?:imum)?)\s*(\$?\s*[0-9][0-9,.]*\s*(?:m|mm|k|million|thousand)?)/i);
  return m ? m[1].replace(/\s+/g, '') : '';
}

function buildListingsFinderMandate(industry, geography, revenue, dealSize, criteria) {
  const ind = String(industry || '').trim();
  const geo = String(geography || '').trim();
  const rev = compactMoney(revenue);
  const cap = priceCap(dealSize, criteria);
  let query = `${ind} in ${geo} for sale`;
  if (cap) query += ` under ${cap}`;
  if (rev) query += ` with revenue over ${rev}`;
  return query;
}
'@

$normalize = Get-Node 'Normalize Intake + Generate Mandate ID'
$normalize.parameters.jsCode = $normalize.parameters.jsCode.Replace(
    "const fullMandateText = ``Find `${industry} businesses for sale in `${geography}. Revenue range: `${revenueRange || 'Not specified'}. EBITDA range: `${ebitdaRange || 'Not specified'}. Deal size: `${dealSize || 'Not specified'}. Acquisition criteria: `${acquisitionCriteria}.``;",
    "$builder`nconst fullMandateText = buildListingsFinderMandate(industry, geography, revenueRange, dealSize, acquisitionCriteria);"
)

$scheduled = Get-Node 'Scheduled - Pick Due Mandate'
$scheduled.parameters.jsCode = $scheduled.parameters.jsCode.Replace(
    "const rows = `$input.all().map(i => i.json);",
    "const rows = `$input.all().map(i => i.json);`n$builder"
)
$scheduled.parameters.jsCode = $scheduled.parameters.jsCode.Replace(
    "mandate_id: r['Mandate ID'],",
    "mandate_id: r['Mandate ID'] || r['Mandate ID B20000'] || r['mandate_id'] || '',"
)
$scheduled.parameters.jsCode = $scheduled.parameters.jsCode.Replace(
    "listingsfinder_mandate: ``Find `${r['Industry']} businesses for sale in `${r['Geography']}. Revenue range: `${r['Revenue Range'] || 'Not specified'}. EBITDA range: `${r['EBITDA Range'] || 'Not specified'}. Deal size: `${r['Deal Size'] || 'Not specified'}. Acquisition criteria: `${r['Acquisition Criteria'] || ''}.``",
    "listingsfinder_mandate: buildListingsFinderMandate(r['Industry'], r['Geography'], r['Revenue Range'], r['Deal Size'], r['Acquisition Criteria'])"
)

foreach ($name in @('ListingsFinder API - Start Search', 'Scheduled - ListingsFinder Search')) {
    $node = Get-Node $name
    $node | Add-Member -NotePropertyName retryOnFail -NotePropertyValue $true -Force
    $node | Add-Member -NotePropertyName maxTries -NotePropertyValue 2 -Force
    $node | Add-Member -NotePropertyName waitBetweenTries -NotePropertyValue 5000 -Force
    foreach ($header in $node.parameters.headerParameters.parameters) {
        if ($header.name -eq 'X-API-Key') {
            $header.value = '={{ $env.LISTINGSFINDER_API_KEY }}'
        }
    }
}

# The API parser now receives a bounded location (`in ... for sale`) and
# parser-supported numeric language (`under`, `revenue over`). With that fixed,
# keep n8n's second geography gate permissive for locations it does not know,
# rather than silently treating Arizona/Utah/etc. as validated matches.
$extract = Get-Node 'Extract ListingsFinder Listings1'
$extract.parameters.jsCode = $extract.parameters.jsCode.Replace(
    "if (mode === 'open') return true;",
    @'
if (mode === 'open') {
    const wanted = lower(mandateGeo)
      .replace(/\b(within|miles?|hours?|of|from|greater|area|region|the)\b/g, ' ')
      .split(/,|\band\b|\bor\b|\//)
      .map(x => x.trim())
      .filter(x => x.length >= 3);
    if (!wanted.length) return true;
    const aliases = [];
    if (/united states|\busa\b/.test(lower(mandateGeo))) aliases.push('united states', 'usa', ' u.s. ');
    if (/greater toronto|\bgta\b/.test(lower(mandateGeo))) aliases.push('greater toronto', 'gta', 'toronto');
    return [...wanted, ...aliases].some(place => text.includes(place));
  }
'@
)

$prepare = Get-Node 'Scheduled - Prepare New Matching Listings'
$old = "function isGeoMatch(l,geo){const t=txt([l.location,l.geo_normalized,l.city,l.state_province,l.country,l.listing_title,l.title,l.description,l.source_url].join(' '));if(negativeGeoTokens(geo).some(x=>t.includes(x.trim())))return false;const toks=mandateGeoTokens(geo);if(!toks.length)return true;if(toks.some(x=>t.includes(x.trim())))return true;if(txt(geo).includes('canada')&&t.includes('canada'))return true;return false;}"
$new = "function isGeoMatch(l,geo){const t=txt([l.location,l.geo_normalized,l.city,l.state_province,l.country,l.listing_title,l.title,l.description,l.source_url].join(' '));if(negativeGeoTokens(geo).some(x=>t.includes(x.trim())))return false;const toks=mandateGeoTokens(geo);if(toks.length)return toks.some(x=>t.includes(x.trim()))||(txt(geo).includes('canada')&&t.includes('canada'));const wanted=txt(geo).replace(/\b(within|miles?|hours?|of|from|greater|area|region|the)\b/g,' ').split(/,|\band\b|\bor\b|\//).map(x=>x.trim()).filter(x=>x.length>=3);const aliases=[];if(/united states|\busa\b/.test(txt(geo)))aliases.push('united states','usa',' u.s. ');if(/greater toronto|\bgta\b/.test(txt(geo)))aliases.push('greater toronto','gta','toronto');return !wanted.length||[...wanted,...aliases].some(x=>t.includes(x));}"
$prepare.parameters.jsCode = $prepare.parameters.jsCode.Replace($old, $new)

# Check every five minutes. The workflow intentionally handles one mandate per
# tick to protect the limited Serper quota, so a queue drains predictably.
$oldTriggerName = 'Schedule Trigger - Check Buy Mandates Every 15 Min'
$newTriggerName = 'Schedule Trigger - Check Buy Mandates Every 5 Min'
$trigger = Get-Node $oldTriggerName
$trigger.parameters.rule.interval[0].minutesInterval = 5
$trigger.name = $newTriggerName
$triggerConnection = $workflow.connections.PSObject.Properties[$oldTriggerName].Value
$workflow.connections | Add-Member -NotePropertyName $newTriggerName -NotePropertyValue $triggerConnection -Force
$workflow.connections.PSObject.Properties.Remove($oldTriggerName)

$workflow | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $OutputPath -Encoding utf8



