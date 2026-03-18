$ErrorActionPreference = 'Stop'
$base = 'http://127.0.0.1:8000'

function LogStep($msg) {
  Write-Host ("`n=== " + $msg + " ===")
}

function LogReq($method, $url, $body) {
  Write-Host ("REQ " + $method + " " + $url)
  if ($body) {
    Write-Host ("BODY " + $body)
  }
}

function LogRes($status, $body) {
  Write-Host ("RES " + $status)
  if ($body) {
    Write-Host ("DATA " + $body)
  }
}

function Assert($cond, $msg) {
  if (-not $cond) {
    throw "ASSERT FAILED: $msg"
  }
}

LogStep '0) Backend health'
LogReq 'GET' "$base/health" $null
$healthResp = Invoke-WebRequest -Method Get -Uri "$base/health" -UseBasicParsing
$health = $healthResp.Content | ConvertFrom-Json
LogRes $healthResp.StatusCode $healthResp.Content
Assert ($health.status -eq 'healthy') 'Backend health not healthy'

$stamp = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$email = "fullpipe_$stamp@example.com"
$password = 'TestPass123!'
$slug = "fullpipe-$stamp"

LogStep '1) Register'
$registerObj = @{ email = $email; password = $password; full_name = 'Full Pipe User'; tenant = @{ name = "Full Pipe Co $stamp"; slug = $slug } }
$registerBody = $registerObj | ConvertTo-Json -Depth 6
LogReq 'POST' "$base/auth/register" $registerBody
$regResp = Invoke-WebRequest -Method Post -Uri "$base/auth/register" -ContentType 'application/json' -Body $registerBody -UseBasicParsing
$reg = $regResp.Content | ConvertFrom-Json
LogRes $regResp.StatusCode ($regResp.Content.Substring(0, [Math]::Min(260, $regResp.Content.Length)))
Assert ($null -ne $reg.access_token) 'Register missing token'

LogStep '2) Login'
$loginBody = @{ email = $email; password = $password } | ConvertTo-Json
LogReq 'POST' "$base/auth/login" $loginBody
$loginResp = Invoke-WebRequest -Method Post -Uri "$base/auth/login" -ContentType 'application/json' -Body $loginBody -UseBasicParsing
$login = $loginResp.Content | ConvertFrom-Json
LogRes $loginResp.StatusCode ($loginResp.Content.Substring(0, [Math]::Min(260, $loginResp.Content.Length)))
Assert ($null -ne $login.access_token) 'Login missing token'
$token = $login.access_token
$authHeader = @{ Authorization = "Bearer $token" }

LogStep '3) Tenant + Stats'
LogReq 'GET' "$base/admin/tenant" $null
$tenantResp = Invoke-WebRequest -Method Get -Uri "$base/admin/tenant" -Headers $authHeader -UseBasicParsing
$tenant = $tenantResp.Content | ConvertFrom-Json
LogRes $tenantResp.StatusCode $tenantResp.Content
Assert ($tenant.slug -eq $slug) 'Tenant slug mismatch'

LogReq 'GET' "$base/admin/stats" $null
$statsResp = Invoke-WebRequest -Method Get -Uri "$base/admin/stats" -Headers $authHeader -UseBasicParsing
LogRes $statsResp.StatusCode $statsResp.Content

LogStep '4) Upload document'
$pdfPath = [IO.Path]::Combine($env:TEMP, "fullpipe-$stamp.pdf")
Invoke-WebRequest -Uri 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf' -OutFile $pdfPath -UseBasicParsing
Write-Host ("FILE " + $pdfPath)
$uploadRaw = curl.exe --max-time 120 -sS -X POST "$base/documents/upload" -H "Authorization: Bearer $token" -F "file=@$pdfPath;type=application/pdf"
Write-Host ("RES 202ish RAW " + $uploadRaw)
$upload = $uploadRaw | ConvertFrom-Json
Assert ($null -ne $upload.id) 'Upload did not return id'
$docId = $upload.id

LogStep '5) Poll documents until ready/failed'
$status = 'pending'
$chunkCount = 0
$pollCount = 0
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 1500
  $pollCount++
  $docsResp = Invoke-WebRequest -Method Get -Uri "$base/documents" -Headers $authHeader -UseBasicParsing
  $docs = $docsResp.Content | ConvertFrom-Json
  $row = $docs.documents | Where-Object { $_.id -eq $docId } | Select-Object -First 1
  if ($row) {
    $status = $row.status
    $chunkCount = [int]$row.chunk_count
    Write-Host ("POLL " + $pollCount + " status=" + $status + " chunks=" + $chunkCount)
    if ($status -eq 'ready' -or $status -eq 'failed') {
      break
    }
  } else {
    Write-Host ("POLL " + $pollCount + ' doc not yet visible')
  }
}
Assert ($status -eq 'ready') ("Ingestion did not reach ready. Final status=" + $status)
Assert ($chunkCount -ge 1) 'Ready doc has chunk_count < 1'

LogStep '6) Chat query (RAG retrieval)'
$chatBody = @{ query = 'Summarize the uploaded PDF in one sentence.' } | ConvertTo-Json
LogReq 'POST' "$base/chat" $chatBody
$chatResp = Invoke-WebRequest -Method Post -Uri "$base/chat" -Headers $authHeader -ContentType 'application/json' -Body $chatBody -UseBasicParsing
$chat = $chatResp.Content | ConvertFrom-Json
LogRes $chatResp.StatusCode ($chatResp.Content.Substring(0, [Math]::Min(400, $chatResp.Content.Length)))
Assert ($chat.answer.Length -gt 0) 'Chat answer empty'
Assert (($chat.sources | Measure-Object).Count -ge 1) 'Chat sources empty'
Assert ($null -ne $chat.conversation_id) 'conversation_id missing'

LogStep '7) Conversations list'
$convsResp = Invoke-WebRequest -Method Get -Uri "$base/chat/conversations" -Headers $authHeader -UseBasicParsing
$convs = $convsResp.Content | ConvertFrom-Json
LogRes $convsResp.StatusCode $convsResp.Content
Assert (($convs | Measure-Object).Count -ge 1) 'No conversations returned'

LogStep '8) Conversation details'
$cid = $chat.conversation_id
$detailResp = Invoke-WebRequest -Method Get -Uri "$base/chat/conversations/$cid" -Headers $authHeader -UseBasicParsing
$detail = $detailResp.Content | ConvertFrom-Json
LogRes $detailResp.StatusCode ($detailResp.Content.Substring(0, [Math]::Min(600, $detailResp.Content.Length)))
Assert (($detail.messages | Measure-Object).Count -ge 2) 'Conversation detail missing user/assistant messages'

LogStep '9) Document delete diagnostics'
LogReq 'DELETE' "$base/documents/$docId" $null
$deleteStatus = 'unknown'
try {
  $delResp = Invoke-WebRequest -Method Delete -Uri "$base/documents/$docId" -Headers $authHeader -UseBasicParsing
  $deleteStatus = "ok:$($delResp.StatusCode)"
  LogRes $delResp.StatusCode $delResp.Content
} catch {
  $code = $_.Exception.Response.StatusCode.value__
  $stream = $_.Exception.Response.GetResponseStream()
  $reader = New-Object System.IO.StreamReader($stream)
  $errBody = $reader.ReadToEnd()
  $deleteStatus = "error:$code"
  Write-Host ("RES " + $code)
  Write-Host ("DATA " + $errBody)
}

LogStep '10) Final list check'
$finalDocsResp = Invoke-WebRequest -Method Get -Uri "$base/documents" -Headers $authHeader -UseBasicParsing
$finalDocs = $finalDocsResp.Content | ConvertFrom-Json
$row2 = $finalDocs.documents | Where-Object { $_.id -eq $docId } | Select-Object -First 1
$visible = $null -ne $row2
Write-Host ("DOC_VISIBLE_AFTER_DELETE=" + $visible)
Write-Host ("FINAL_DOCS_TOTAL=" + $finalDocs.total)

Write-Host "`nPIPELINE_SUMMARY email=$email tenantSlug=$slug docId=$docId status=$status chunks=$chunkCount sources=$((($chat.sources | Measure-Object).Count)) delete=$deleteStatus"
Write-Host 'E2E_FRONTEND_STYLE_PIPELINE_DONE'
