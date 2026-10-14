<#
.SYNOPSIS
  Windows equivalent of the Makefile:  .\tasks.ps1 <target> [-ComposeProfile oracle|graph|llm|full] [-Gpu]
#>
param(
    [Parameter(Position = 0)][string]$Target = "status",
    [string]$ComposeProfile = "oracle",
    [switch]$Gpu  # adds docker-compose.gpu.yml so Ollama runs on an NVIDIA GPU
)
$ErrorActionPreference = "Stop"

function Invoke-Step([string]$exe, [string[]]$argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { throw "'$exe $($argv -join ' ')' failed with exit code $LASTEXITCODE" }
}

$amlCommands = @("status", "retention", "data", "load", "screen", "er", "monitor", "graph", "bench", "score", "ui")

switch ($Target) {
    "up"   {
        $files = if ($Gpu) { @("-f", "docker-compose.yml", "-f", "docker-compose.gpu.yml") } else { @() }
        Invoke-Step docker (@("compose") + $files + @("--profile", $ComposeProfile, "up", "-d"))
    }
    "down" { Invoke-Step docker @("compose", "--profile", "full", "down") }
    "init" { Invoke-Step uv @("run", "aml", "init-db") }
    "test" { Invoke-Step uv @("run", "pytest") }
    "lint" {
        Invoke-Step uv @("run", "ruff", "check", ".")
        Invoke-Step uv @("run", "ruff", "format", "--check", ".")
    }
    "all" {
        foreach ($t in @("data", "load", "screen", "er", "monitor", "graph", "score")) {
            Invoke-Step uv @("run", "aml", $t)
        }
        Invoke-Step uv @("run", "aml", "rag", "build")
    }
    "rag"  { Invoke-Step uv @("run", "aml", "rag", "build") }
    default {
        if ($amlCommands -contains $Target) { Invoke-Step uv @("run", "aml", $Target) }
        else { throw "Unknown target '$Target'" }
    }
}
