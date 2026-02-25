param(
  [string]$BaseUrl = "http://localhost:8000",
  [string]$TenantId = "tenant_demo",
  [string]$StoreId = "store_001",
  [string]$SourceSystem = "pos_sim",
  [string]$SchemaVersion = "1.0"
)

$ErrorActionPreference = "Stop"

function Post-Event {
  param(
    [Parameter(Mandatory=$true)][hashtable]$Event
  )

  $json = ($Event | ConvertTo-Json -Depth 20)
  try {
    $resp = Invoke-WebRequest -Method Post -Uri "$BaseUrl/v1/events" -ContentType "application/json" -Body $json
    Write-Host ""
    Write-Host "POST /v1/events -> $($resp.StatusCode)" -ForegroundColor Green
    Write-Host $resp.Content
  } catch {
    $status = $_.Exception.Response.StatusCode.value__ 2>$null
    Write-Host ""
    Write-Host "POST /v1/events -> $status" -ForegroundColor Yellow
    try {
      $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
      $body = $reader.ReadToEnd()
      Write-Host $body
    } catch {
      Write-Host $_
    }
  }
}

function Get-Health {
  $resp = Invoke-WebRequest -Method Get -Uri "$BaseUrl/v1/health"
  Write-Host ""
  Write-Host "GET /v1/health -> $($resp.StatusCode)" -ForegroundColor Cyan
  Write-Host $resp.Content
}

function Get-Open-Exceptions {
  $uri = "$BaseUrl/v1/exceptions?status=open&tenant_id=$TenantId&limit=50"
  $resp = Invoke-WebRequest -Method Get -Uri $uri
  Write-Host ""
  Write-Host "GET /v1/exceptions?status=open -> $($resp.StatusCode)" -ForegroundColor Cyan
  Write-Host $resp.Content
}

# -------------------
# Demo event payloads
# -------------------
$occurredAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

# 1) First arrival: processed (201)
$sale = @{
  schema_version  = $SchemaVersion
  tenant_id       = $TenantId
  store_id        = $StoreId
  source_system   = $SourceSystem
  event_id        = "evt-1001"
  source_event_id = "src-1001"
  event_type      = "SALE"
  occurred_at     = $occurredAt
  txn_id          = "txn-9001"
  currency        = "USD"
  total_amount    = 42.50
  line_items      = @(
    @{ sku="SKU-AAA"; qty=1; amount=30.00 },
    @{ sku="SKU-BBB"; qty=1; amount=12.50 }
  )
}

# 2) Exact retry: duplicate (200)
$saleDuplicate = $sale.Clone()

# 3) Conflicting duplicate: quarantined (202, IDEMPOTENCY_CONFLICT)
$saleConflict = $sale.Clone()
$saleConflict["total_amount"] = 41.00
$saleConflict["line_items"] = @(
  @{ sku="SKU-AAA"; qty=1; amount=28.50 },
  @{ sku="SKU-BBB"; qty=1; amount=12.50 }
)

# 4) Unknown event type: quarantined (202, UNKNOWN_EVENT_TYPE)
$unknownType = $sale.Clone()
$unknownType["event_id"] = "evt-2001"
$unknownType["source_event_id"] = "src-2001"
$unknownType["event_type"] = "MAGIC_EVENT"

Write-Host ""
Write-Host "Ledger-Safe demo: processed -> duplicate -> conflict quarantine -> unknown type quarantine" -ForegroundColor White
Write-Host "BaseUrl: $BaseUrl | TenantId: $TenantId" -ForegroundColor DarkGray

Get-Health

Post-Event -Event $sale
Post-Event -Event $saleDuplicate
Post-Event -Event $saleConflict
Post-Event -Event $unknownType

Get-Health
Get-Open-Exceptions

Write-Host ""
Write-Host "Next: open the Ops Console and review the Exceptions Queue:" -ForegroundColor White
Write-Host "http://localhost:8501" -ForegroundColor White
