param(
    [switch]$Services,
    [switch]$Browser
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    $nodeTests = @(Get-ChildItem -LiteralPath tests -Filter '*.test.cjs' -File | ForEach-Object FullName)
    & node --test @nodeTests
    if ($LASTEXITCODE -ne 0) { throw 'Node 回归未通过' }
    & npm --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { throw '前端构建未通过' }

    if ($Services) {
        $serviceContainers = @{
            backend = 'xianyu-codex-local-backend-web-1'
            websocket = 'xianyu-codex-local-websocket-1'
            scheduler = 'xianyu-codex-local-scheduler-1'
        }
        foreach ($service in @('backend', 'websocket', 'scheduler')) {
            $container = $serviceContainers[$service]
            $testRunDirectory = "/tmp/xianyu-regression-$([guid]::NewGuid().ToString('N'))"
            try {
                & docker exec $container mkdir -p $testRunDirectory
                if ($LASTEXITCODE -ne 0) { throw "无法创建 $service 回归目录" }
                & docker cp tests/. "${container}:$testRunDirectory"
                if ($LASTEXITCODE -ne 0) { throw "无法准备 $service 回归" }
                & docker exec -e PYTHONPATH=/app -w /app $container python "$testRunDirectory/run_service_tests.py" $service
                if ($LASTEXITCODE -ne 0) { throw "$service 回归未通过" }
            } finally {
                # 只清理由本次运行创建的/tmp专用目录，禁止删除其他位置。
                & docker exec $container python -c "import pathlib, re, shutil, sys; p=pathlib.Path(sys.argv[1]); assert p.parent == pathlib.Path('/tmp') and re.fullmatch(r'xianyu-regression-[0-9a-f]{32}', p.name); shutil.rmtree(p, ignore_errors=True)" $testRunDirectory
            }
        }
    }

    if ($Browser) {
        # 9001须服务本工作区编译的frontend/dist；脚本内所有API均被模拟。
        $servedIndex = (Invoke-WebRequest -Uri http://127.0.0.1:9001 -TimeoutSec 10).Content
        $builtIndex = [System.IO.File]::ReadAllText((Join-Path $projectRoot 'frontend/dist/index.html'))
        if ($servedIndex.Trim() -cne $builtIndex.Trim()) { throw '9001当前页面与本工作区构建不一致，请先配置9001服务此frontend/dist' }
        New-Item -ItemType Directory -Force -Path output/playwright | Out-Null
        foreach ($name in @('publish-lists.js', 'batch-material-pager.js', 'publish-history.js')) {
            $sessionName = "publish-regression-$PID"
            try {
                & npx --yes --package @playwright/cli playwright-cli "-s=$sessionName" open about:blank
                if ($LASTEXITCODE -ne 0) { throw '无法启动浏览器回归' }
                $result = & npx --yes --package @playwright/cli playwright-cli "-s=$sessionName" --json run-code --filename "tests/browser/$name"
                $exitCode = $LASTEXITCODE
                $response = ($result -join "`n") | ConvertFrom-Json
                if ($exitCode -ne 0 -or $response.isError -or !$response.result) { throw "$name 浏览器回归未通过：$($response.error)" }
                Write-Output "$name : $($response.result)"
            } finally {
                & npx --yes --package @playwright/cli playwright-cli "-s=$sessionName" close
            }
        }
    }
} finally {
    Pop-Location
}
