param(
    [Parameter(Mandatory=$true)][ValidateRange(1,65535)][int]$Port,
    [string]$DesktopBin = 'C:\Program Files\Microsoft Power BI Desktop\bin'
)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$casesPath=Join-Path $projectRoot 'reports\analysis\powerbi_dax_cases.json'
$outputPath=Join-Path $projectRoot 'reports\analysis\powerbi_validation.json'
$assemblyPath=Join-Path $DesktopBin 'Microsoft.PowerBI.AdomdClient.dll'
[System.Reflection.Assembly]::LoadFrom($assemblyPath) | Out-Null
[System.Reflection.Assembly]::LoadFrom((Join-Path $DesktopBin 'Microsoft.PowerBI.Tabular.dll')) | Out-Null
$definitionPath=Join-Path $projectRoot 'dashboards\powerbi\Recruitment.SemanticModel\model.bim'
$definition=Get-Content -LiteralPath $definitionPath -Raw -Encoding UTF8 | ConvertFrom-Json
$tomServer=New-Object Microsoft.AnalysisServices.Tabular.Server
$tomServer.Connect("localhost:$Port")
try {
    $models=@($tomServer.Databases | Where-Object { $_.Model.Tables.Contains('Jobs') -and $_.Model.Tables.Contains('Builds') })
    if ($models.Count -ne 1) { throw 'The selected endpoint must contain exactly one Recruitment model' }
    $catalog=$models[0].Name
    $loadedModel=$models[0].Model
    foreach($tableDefinition in $definition.model.tables) {
        $table=$loadedModel.Tables[$tableDefinition.name]
        if ($null -eq $table) { throw "Missing table: $($tableDefinition.name)" }
        $expectedExpression=$tableDefinition.partitions[0].source.expression
        if ($expectedExpression -is [array]) { $expectedExpression=$expectedExpression -join "`n" }
        if ($table.Partitions[0].Source.Expression.Replace("`r`n","`n") -cne $expectedExpression.Replace("`r`n","`n")) {
            throw "Loaded Power Query differs from Git definition: $($tableDefinition.name)"
        }
        foreach($measureDefinition in $tableDefinition.measures) {
            $expectedMeasure=$measureDefinition.expression
            if ($expectedMeasure -is [array]) { $expectedMeasure=$expectedMeasure -join "`n" }
            if ($table.Measures[$measureDefinition.name].Expression.Replace("`r`n","`n") -cne $expectedMeasure.Replace("`r`n","`n")) {
                throw "Loaded DAX differs from Git definition: $($measureDefinition.name)"
            }
        }
    }
} finally { $tomServer.Disconnect() }
$connection=New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$Port;Initial Catalog=$catalog")
$connection.Open()
try {
    $cases=Get-Content -LiteralPath $casesPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $results=@()
    foreach($case in $cases.cases) {
        $command=$connection.CreateCommand()
        $command.CommandTimeout=60
        $command.CommandText=$case.dax
        $reader=$command.ExecuteReader()
        try {
            if (-not $reader.Read()) { throw "No DAX row: $($case.name)" }
            $actual=@{}
            for($i=0;$i -lt $reader.FieldCount;$i++) {
                $name=$reader.GetName($i).Trim('[',']')
                $actual[$name]=if($reader.IsDBNull($i)) { $null } else { $reader.GetValue($i) }
            }
        } finally { $reader.Close() }
        foreach($property in $case.expected.PSObject.Properties) {
            $actualValue=$actual[$property.Name]
            if ($null -eq $property.Value) {
                if ($null -ne $actualValue) { throw "$($case.name): $($property.Name) should be BLANK" }
            } elseif ($null -eq $actualValue -or [Math]::Abs([double]$actualValue-[double]$property.Value) -gt 0.000000001) {
                throw "$($case.name): $($property.Name) expected $($property.Value), actual $actualValue"
            }
        }
        $results+=@{name=$case.name;actual=$actual;passed=$true}
    }
    $record=@{status='passed';checked_at_utc=[DateTime]::UtcNow.ToString('o');
        case_count=$results.Count;builds=$cases.builds;
        model_definition_sha256=(Get-FileHash -LiteralPath $definitionPath -Algorithm SHA256).Hash.ToLower();
        cases_sha256=(Get-FileHash -LiteralPath $casesPath -Algorithm SHA256).Hash.ToLower();results=$results}
    $recordJson=($record | ConvertTo-Json -Depth 12).Replace("`r`n","`n")
    [System.IO.File]::WriteAllText($outputPath,$recordJson+"`n",[System.Text.UTF8Encoding]::new($false))
    Write-Output "Power BI DAX: $($results.Count) cases passed. $outputPath"
} finally { $connection.Close() }
